#include "belt_fsm.h"
#include "board_gpio.h"

/*
   Logic hien tai sau update:
   - So 1/2 trong lenh ROS2 duoc hieu la ID bang tai.
   - $CMD,START,1: chi arm/load bang tai 1, chi nhan S1/S3.
   - $CMD,START,2: chi arm/load bang tai 2, chi nhan S2/S4.
   - $CMD,STOP,1,LEFT/RIGHT: chi tra hang bang tai 1, chi dung S1/S3.
   - $CMD,STOP,2,LEFT/RIGHT: chi tra hang bang tai 2, chi dung S2/S4.
   - Hai bang tai doc lap: co the gui lenh cho belt 1 va belt 2 gan nhu cung luc.
   - Cam bien cua bang tai khac bi bo qua hoan toan.
   - Nut START/RUN vat ly khong dung logic ROS2; no bat che do AUTO LIEN TUC cho ca 2 bang tai:
     + Bang tai 1: S1 <-> S3
     + Bang tai 2: S2 <-> S4
     + Moi bang tai doc cap cam bien rieng, giong logic code cu.
   - ROS2 unload co debounce 150ms khi cam bien dich mat tin hieu de chong vat tron/truot gay nhay cam bien.
   - Nut STOP vat ly tao STOP_LOCK:
     + Dung toan bo relay.
     + ROS2 khong duoc chay tiep khi dang STOP_LOCK.
     + Chi nut RESET vat ly hoac START/RUN vat ly moi mo khoa.
     + Moi cap nguon, bam RESET khong lam bang tai chay; phai bam START/RUN.
*/

typedef enum {
  MODE_IDLE = 0,
  MODE_LOAD_ARMED,
  MODE_LOAD_MOVING,
  MODE_UNLOAD_MOVING,

  /* Che do nut RUN vat ly rieng cho bang tai 1, giong logic code cu S1 <-> S3 */
  MODE_PHYSICAL_ARMED,
  MODE_PHYSICAL_MOVING,
  MODE_PHYSICAL_HOLD
} BeltMode_t;

typedef struct {
  BeltMode_t mode;
  uint8_t source_sensor;      /* 1..4 */
  uint8_t target_sensor;      /* 1..4 */
  uint8_t exit_sensor;        /* 1..4 */
  uint8_t exit_seen;
  uint8_t exit_inactive_pending;
  uint32_t exit_inactive_tick;
  uint8_t cargo_valid;
  uint8_t cargo_sensor;       /* vi tri hang da luu tren belt */
  BeltDirection_t dir;
  BeltSide_t unload_side;
} BeltRuntime_t;

#define MAX_BELTS                 2U
#define EVENT_Q_SIZE              8U
#define UNLOAD_EXIT_DEBOUNCE_MS   150U  /* Cam bien dich phai mat lien tuc 150ms moi xac nhan da roi bang tai */

static SystemState_t s_state = SYS_BOOT;
static uint8_t s_estop_source = 0U;
static uint8_t s_stop_locked = 0U;   /* 1 = da bam STOP vat ly, cho RESET/START vat ly mo khoa */
static BeltRuntime_t s_belt[MAX_BELTS + 1U]; /* index 1..2 */

static BeltEvent_t s_evt_q[EVENT_Q_SIZE];
static uint8_t s_evt_head = 0U;
static uint8_t s_evt_tail = 0U;

/* ================= EVENT QUEUE ================= */

static void push_event(BeltEventType_t type, uint8_t belt_id, BeltSide_t side)
{
  uint8_t next = (uint8_t)((s_evt_head + 1U) % EVENT_Q_SIZE);

  if (next == s_evt_tail) {
    s_evt_tail = (uint8_t)((s_evt_tail + 1U) % EVENT_Q_SIZE);
  }

  s_evt_q[s_evt_head].type = type;
  s_evt_q[s_evt_head].cmd_id = belt_id;
  s_evt_q[s_evt_head].side = side;
  s_evt_head = next;
}

uint8_t Belt_PopEvent(BeltEvent_t *ev)
{
  if (s_evt_tail == s_evt_head) {
    return 0U;
  }

  if (ev != 0) {
    *ev = s_evt_q[s_evt_tail];
  }

  s_evt_tail = (uint8_t)((s_evt_tail + 1U) % EVENT_Q_SIZE);
  return 1U;
}

/* ================= SENSOR HELPERS ================= */

static uint8_t belt_id_valid(uint8_t belt_id)
{
  return (belt_id >= 1U && belt_id <= MAX_BELTS) ? 1U : 0U;
}

static uint8_t sensor_active_by_id(uint8_t sensor_id)
{
  switch (sensor_id) {
  case 1U: return Board_S1();
  case 2U: return Board_S2();
  case 3U: return Board_S3();
  case 4U: return Board_S4();
  default: return 0U;
  }
}

static uint8_t sensor_to_belt(uint8_t sensor_id)
{
  if (sensor_id == 1U || sensor_id == 3U) {
    return 1U;
  }

  if (sensor_id == 2U || sensor_id == 4U) {
    return 2U;
  }

  return 0U;
}

static uint8_t opposite_sensor(uint8_t sensor_id)
{
  switch (sensor_id) {
  case 1U: return 3U;
  case 3U: return 1U;
  case 2U: return 4U;
  case 4U: return 2U;
  default: return 0U;
  }
}

static uint8_t first_active_sensor_on_belt(uint8_t belt_id)
{
  if (belt_id == 1U) {
    if (Board_S1()) { return 1U; }
    if (Board_S3()) { return 3U; }
  } else if (belt_id == 2U) {
    if (Board_S2()) { return 2U; }
    if (Board_S4()) { return 4U; }
  }

  return 0U;
}

static uint8_t exit_sensor_for_side(uint8_t belt_id, BeltSide_t side)
{
  if (belt_id == 1U) {
    return (side == BELT_SIDE_LEFT) ? 1U : 3U;
  }

  if (belt_id == 2U) {
    return (side == BELT_SIDE_LEFT) ? 2U : 4U;
  }

  return 0U;
}

static BeltDirection_t direction_towards_sensor(uint8_t target_sensor)
{
  /*
     Theo mapping board_gpio.c hien tai:
     - Belt 1: BELT_DIR_LEFT  = PA11 = S1 -> S3
               BELT_DIR_RIGHT = PA12 = S3 -> S1
     - Belt 2: BELT_DIR_LEFT  = PB3  = S2 -> S4
               BELT_DIR_RIGHT = PA15 = S4 -> S2
  */
  if (target_sensor == 3U || target_sensor == 4U) {
    return BELT_DIR_LEFT;
  }

  return BELT_DIR_RIGHT;
}

static void run_belt_towards_sensor(uint8_t belt_id, uint8_t sensor_id)
{
  BeltDirection_t dir = direction_towards_sensor(sensor_id);

  if (belt_id_valid(belt_id)) {
    s_belt[belt_id].dir = dir;
    Board_BeltRun(belt_id, dir);
  }
}

static uint8_t any_belt_running_or_armed(void)
{
  uint8_t i;

  for (i = 1U; i <= MAX_BELTS; i++) {
    if (s_belt[i].mode != MODE_IDLE) {
      return 1U;
    }
  }

  return 0U;
}

static void refresh_system_state(void)
{
  if (s_state == SYS_ESTOP) {
    return;
  }

  if (s_stop_locked) {
    s_state = SYS_IDLE;
    return;
  }

  s_state = any_belt_running_or_armed() ? SYS_RUNNING : SYS_IDLE;
}

static void reset_belt_runtime(uint8_t belt_id)
{
  if (!belt_id_valid(belt_id)) {
    return;
  }

  s_belt[belt_id].mode = MODE_IDLE;
  s_belt[belt_id].source_sensor = 0U;
  s_belt[belt_id].target_sensor = 0U;
  s_belt[belt_id].exit_sensor = 0U;
  s_belt[belt_id].exit_seen = 0U;
  s_belt[belt_id].exit_inactive_pending = 0U;
  s_belt[belt_id].exit_inactive_tick = 0U;
  s_belt[belt_id].dir = BELT_DIR_LEFT;
  s_belt[belt_id].unload_side = BELT_SIDE_LEFT;

  Board_BeltStop(belt_id);
}

/* ================= PUBLIC ================= */

void Belt_Init(void)
{
  uint8_t i;

  s_state = SYS_IDLE;
  s_estop_source = 0U;
  s_stop_locked = 0U;

  for (i = 1U; i <= MAX_BELTS; i++) {
    s_belt[i].mode = MODE_IDLE;
    s_belt[i].source_sensor = 0U;
    s_belt[i].target_sensor = 0U;
    s_belt[i].exit_sensor = 0U;
    s_belt[i].exit_seen = 0U;
    s_belt[i].exit_inactive_pending = 0U;
    s_belt[i].exit_inactive_tick = 0U;
    s_belt[i].cargo_valid = 0U;
    s_belt[i].cargo_sensor = 0U;
    s_belt[i].dir = BELT_DIR_LEFT;
    s_belt[i].unload_side = BELT_SIDE_LEFT;
  }

  s_evt_head = 0U;
  s_evt_tail = 0U;

  Board_RelayAllOff();
}

SystemState_t Belt_GetState(void)
{
  return s_state;
}

uint8_t Belt_GetActiveBelt(void)
{
  uint8_t mask = 0U;

  if (s_belt[1U].mode != MODE_IDLE) {
    mask |= 1U;
  }

  if (s_belt[2U].mode != MODE_IDLE) {
    mask |= 2U;
  }

  return mask;
}

BeltDirection_t Belt_GetDirection(void)
{
  if (s_belt[1U].mode != MODE_IDLE) {
    return s_belt[1U].dir;
  }

  if (s_belt[2U].mode != MODE_IDLE) {
    return s_belt[2U].dir;
  }

  return BELT_DIR_LEFT;
}

uint8_t Belt_GetEstopSource(void)
{
  return s_estop_source;
}

uint8_t Belt_HasCargo(uint8_t belt_id)
{
  if (belt_id_valid(belt_id)) {
    return s_belt[belt_id].cargo_valid;
  }

  return 0U;
}

uint8_t Belt_SensorAudioEnabled(void)
{
  return 0U;
}

void Belt_TriggerEstop(uint8_t source_code)
{
  uint8_t i;

  s_state = SYS_ESTOP;
  s_estop_source = source_code;

  for (i = 1U; i <= MAX_BELTS; i++) {
    s_belt[i].mode = MODE_IDLE;
    s_belt[i].source_sensor = 0U;
    s_belt[i].target_sensor = 0U;
    s_belt[i].exit_sensor = 0U;
    s_belt[i].exit_seen = 0U;
    s_belt[i].exit_inactive_pending = 0U;
    s_belt[i].exit_inactive_tick = 0U;
  }

  Board_RelayAllOff();
}

uint8_t Belt_TryResetEstop(void)
{
  uint8_t i;

  if (s_state != SYS_ESTOP) {
    return 0U;
  }

  if (HAL_GPIO_ReadPin(BTN_EMER_PORT, BTN_EMER_PIN) == BTN_EMER_ACTIVE) {
    return 0U;
  }

  s_state = SYS_IDLE;
  s_estop_source = 0U;
  s_stop_locked = 0U;

  for (i = 1U; i <= MAX_BELTS; i++) {
    reset_belt_runtime(i);
  }

  Board_RelayAllOff();
  return 1U;
}

uint8_t Belt_OnResetButton(void)
{
  /*
     RESET vat ly:
     - Neu dang ESTOP va nut emergency da nha -> reset ESTOP.
     - Neu dang STOP_LOCK do nut STOP vat ly -> chi mo khoa, KHONG chay bang tai.
     - Neu moi cap nguon/chua bam STOP/chua ESTOP -> khong lam gi.
  */
  if (s_state == SYS_ESTOP) {
    return Belt_TryResetEstop() ? 1U : 0U;
  }

	if (s_stop_locked) {
		Belt_OnStartButton();
		return 2U;
	}

  return 0U;
}

uint8_t Belt_IsStopLocked(void)
{
  return s_stop_locked;
}

void Belt_OnStopButton(void)
{
  uint8_t i;

  /*
     STOP vat ly:
     - Dung tat ca relay.
     - Xoa mode dang chay cua ca 2 bang tai.
     - Dat STOP_LOCK = 1.
     - Sau do chi RESET vat ly hoac START/RUN vat ly moi mo khoa.
  */
  Board_RelayAllOff();

  if (s_state != SYS_ESTOP) {
    for (i = 1U; i <= MAX_BELTS; i++) {
      s_belt[i].mode = MODE_IDLE;
      s_belt[i].source_sensor = 0U;
      s_belt[i].target_sensor = 0U;
      s_belt[i].exit_sensor = 0U;
      s_belt[i].exit_seen = 0U;
      s_belt[i].exit_inactive_pending = 0U;
      s_belt[i].exit_inactive_tick = 0U;
    }

    s_stop_locked = 1U;
    s_state = SYS_IDLE;
  }
}

void Belt_OnStartButton(void)
{
  /*
     Nut START/RUN vat ly theo yeu cau moi:
     - Bat che do AUTO LIEN TUC cho CA 2 bang tai neu bang tai do dang ranh.
     - Bang tai 1 doc S1/S3 va chay qua lai giong code cu.
     - Bang tai 2 doc S2/S4 va chay qua lai giong code cu.
     - Moi bang tai hoat dong doc lap:
       + Belt 1: S1 -> S3 -> HOLD, mat S3 thi cho chu ky moi.
                 S3 -> S1 -> HOLD, mat S1 thi cho chu ky moi.
       + Belt 2: S2 -> S4 -> HOLD, mat S4 thi cho chu ky moi.
                 S4 -> S2 -> HOLD, mat S2 thi cho chu ky moi.
     - Che do nay chay lien tuc cho den khi nhan STOP / ESTOP / BUMPER.
     - Neu mot bang tai dang ban boi lenh ROS2 thi khong reset bang tai do.
  */
  uint8_t belt_id;

  if (s_state == SYS_ESTOP) {
    return;
  }

  /* START/RUN vat ly duoc phep mo khoa sau khi da bam STOP vat ly. */
  if (s_stop_locked) {
    s_stop_locked = 0U;
  }

  for (belt_id = 1U; belt_id <= MAX_BELTS; belt_id++) {
    if (s_belt[belt_id].mode == MODE_IDLE) {
      reset_belt_runtime(belt_id);
      s_belt[belt_id].cargo_valid = 0U;
      s_belt[belt_id].cargo_sensor = 0U;
      s_belt[belt_id].source_sensor = 0U;
      s_belt[belt_id].target_sensor = 0U;
      s_belt[belt_id].exit_sensor = 0U;
      s_belt[belt_id].exit_seen = 0U;
      s_belt[belt_id].exit_inactive_pending = 0U;
      s_belt[belt_id].exit_inactive_tick = 0U;
      s_belt[belt_id].mode = MODE_PHYSICAL_ARMED;
      Board_BeltStop(belt_id);
    }
  }

  refresh_system_state();
}

BeltCmdResult_t Belt_CmdStartLoad(uint8_t belt_id)
{
  if (!belt_id_valid(belt_id)) {
    return BELT_CMD_INVALID;
  }

  if (s_state == SYS_ESTOP) {
    return BELT_CMD_ESTOP;
  }

  if (s_stop_locked) {
    return BELT_CMD_STOP_LOCK;
  }

  if (s_belt[belt_id].mode != MODE_IDLE) {
    return BELT_CMD_BUSY;
  }

  reset_belt_runtime(belt_id);

  /* Bat dau job load moi tren belt nay thi xoa trang thai hang cu cua belt do. */
  s_belt[belt_id].cargo_valid = 0U;
  s_belt[belt_id].cargo_sensor = 0U;

  s_belt[belt_id].mode = MODE_LOAD_ARMED;
  s_belt[belt_id].source_sensor = 0U;
  s_belt[belt_id].target_sensor = 0U;
  s_belt[belt_id].exit_sensor = 0U;
  s_belt[belt_id].exit_seen = 0U;
  s_belt[belt_id].exit_inactive_pending = 0U;
  s_belt[belt_id].exit_inactive_tick = 0U;

  s_state = SYS_RUNNING;

  Board_BeltStop(belt_id);
  return BELT_CMD_OK;
}

BeltCmdResult_t Belt_CmdUnload(uint8_t belt_id, BeltSide_t side)
{
  uint8_t sensor_id;
  uint8_t exit_sensor;

  if (!belt_id_valid(belt_id)) {
    return BELT_CMD_INVALID;
  }

  if (s_state == SYS_ESTOP) {
    return BELT_CMD_ESTOP;
  }

  if (s_stop_locked) {
    return BELT_CMD_STOP_LOCK;
  }

  if (s_belt[belt_id].mode != MODE_IDLE) {
    return BELT_CMD_BUSY;
  }

  sensor_id = 0U;

  if (s_belt[belt_id].cargo_valid &&
      sensor_active_by_id(s_belt[belt_id].cargo_sensor) &&
      sensor_to_belt(s_belt[belt_id].cargo_sensor) == belt_id) {
    sensor_id = s_belt[belt_id].cargo_sensor;
  } else {
    sensor_id = first_active_sensor_on_belt(belt_id);
  }

  if (sensor_id == 0U) {
    return BELT_CMD_NO_CARGO;
  }

  exit_sensor = exit_sensor_for_side(belt_id, side);
  if (exit_sensor == 0U) {
    return BELT_CMD_INVALID;
  }

  s_belt[belt_id].mode = MODE_UNLOAD_MOVING;
  s_belt[belt_id].unload_side = side;
  s_belt[belt_id].source_sensor = sensor_id;
  s_belt[belt_id].target_sensor = 0U;
  s_belt[belt_id].exit_sensor = exit_sensor;
  s_belt[belt_id].exit_seen = sensor_active_by_id(exit_sensor);
  s_belt[belt_id].exit_inactive_pending = 0U;
  s_belt[belt_id].exit_inactive_tick = 0U;

  s_state = SYS_RUNNING;

  run_belt_towards_sensor(belt_id, exit_sensor);
  return BELT_CMD_OK;
}

/* ================= TICK ================= */

static void tick_load_armed(uint8_t belt_id)
{
  uint8_t sensor_id;
  uint8_t target_sensor;

  sensor_id = first_active_sensor_on_belt(belt_id);
  if (sensor_id == 0U) {
    Board_BeltStop(belt_id);
    return;
  }

  target_sensor = opposite_sensor(sensor_id);
  if (target_sensor == 0U || sensor_to_belt(target_sensor) != belt_id) {
    reset_belt_runtime(belt_id);
    return;
  }

  s_belt[belt_id].source_sensor = sensor_id;
  s_belt[belt_id].target_sensor = target_sensor;

  push_event(BELT_EVENT_LOAD_STARTED, belt_id, BELT_SIDE_LEFT);

  run_belt_towards_sensor(belt_id, target_sensor);
  s_belt[belt_id].mode = MODE_LOAD_MOVING;
}

static void tick_load_moving(uint8_t belt_id)
{
  uint8_t target_sensor = s_belt[belt_id].target_sensor;

  if (target_sensor == 0U) {
    reset_belt_runtime(belt_id);
    return;
  }

  if (sensor_active_by_id(target_sensor)) {
    Board_BeltStop(belt_id);

    s_belt[belt_id].cargo_valid = 1U;
    s_belt[belt_id].cargo_sensor = target_sensor;

    push_event(BELT_EVENT_LOAD_STOPPED, belt_id, BELT_SIDE_LEFT);

    s_belt[belt_id].mode = MODE_IDLE;
    s_belt[belt_id].source_sensor = 0U;
    s_belt[belt_id].target_sensor = 0U;
  }
}

static void tick_unload_moving(uint8_t belt_id)
{
  uint8_t exit_sensor = s_belt[belt_id].exit_sensor;

  if (exit_sensor == 0U) {
    reset_belt_runtime(belt_id);
    return;
  }

  /* Luon giu belt chay ve huong cam bien thoat trong luc unload. */
  run_belt_towards_sensor(belt_id, exit_sensor);

  if (s_belt[belt_id].exit_seen == 0U) {
    if (sensor_active_by_id(exit_sensor)) {
      s_belt[belt_id].exit_seen = 1U;
      s_belt[belt_id].exit_inactive_pending = 0U;
      s_belt[belt_id].exit_inactive_tick = 0U;
    }

    return;
  }

  /*
     Chong doi cam bien khi tra hang:
     - Truoc day chi can cam bien dich mat tin hieu 1 lan la dung ngay.
     - Chai nuoc/vat tron bi truot co the lam cam bien nhay mat tin hieu rat ngan,
       STM32 tuong da roi bang tai va gui ACK STOP qua som.
     - Nay yeu cau cam bien dich phai mat tin hieu LIEN TUC 150ms moi dung.
     - Neu trong 150ms cam bien thay lai vat, huy bo bo dem va tiep tuc chay.
  */
  if (sensor_active_by_id(exit_sensor)) {
    s_belt[belt_id].exit_inactive_pending = 0U;
    s_belt[belt_id].exit_inactive_tick = 0U;
    return;
  }

  if (s_belt[belt_id].exit_inactive_pending == 0U) {
    s_belt[belt_id].exit_inactive_pending = 1U;
    s_belt[belt_id].exit_inactive_tick = HAL_GetTick();
    return;
  }

  if ((HAL_GetTick() - s_belt[belt_id].exit_inactive_tick) < UNLOAD_EXIT_DEBOUNCE_MS) {
    return;
  }

  Board_BeltStop(belt_id);

  s_belt[belt_id].cargo_valid = 0U;
  s_belt[belt_id].cargo_sensor = 0U;

  push_event(BELT_EVENT_UNLOAD_DONE, belt_id, s_belt[belt_id].unload_side);

  s_belt[belt_id].mode = MODE_IDLE;
  s_belt[belt_id].source_sensor = 0U;
  s_belt[belt_id].target_sensor = 0U;
  s_belt[belt_id].exit_sensor = 0U;
  s_belt[belt_id].exit_seen = 0U;
  s_belt[belt_id].exit_inactive_pending = 0U;
  s_belt[belt_id].exit_inactive_tick = 0U;
}


static uint8_t physical_left_sensor(uint8_t belt_id)
{
  if (belt_id == 1U) {
    return 1U;   /* Belt 1 LEFT = S1 */
  }

  if (belt_id == 2U) {
    return 2U;   /* Belt 2 LEFT = S2 */
  }

  return 0U;
}

static uint8_t physical_right_sensor(uint8_t belt_id)
{
  if (belt_id == 1U) {
    return 3U;   /* Belt 1 RIGHT = S3 */
  }

  if (belt_id == 2U) {
    return 4U;   /* Belt 2 RIGHT = S4 */
  }

  return 0U;
}

static void tick_physical_armed(uint8_t belt_id)
{
  uint8_t left_sensor;
  uint8_t right_sensor;
  uint8_t target_sensor;

  if (!belt_id_valid(belt_id)) {
    return;
  }

  left_sensor = physical_left_sensor(belt_id);
  right_sensor = physical_right_sensor(belt_id);

  if (left_sensor == 0U || right_sensor == 0U) {
    reset_belt_runtime(belt_id);
    return;
  }

  /*
     Giong code cu:
     - Chi chay khi chi co mot dau co tin hieu.
     - Neu 2 dau cung active thi khong tu chon huong de tranh chay sai.
     Belt 1: S1 -> S3, S3 -> S1.
     Belt 2: S2 -> S4, S4 -> S2.
  */
  if (sensor_active_by_id(left_sensor) && !sensor_active_by_id(right_sensor)) {
    target_sensor = right_sensor;
  } else if (sensor_active_by_id(right_sensor) && !sensor_active_by_id(left_sensor)) {
    target_sensor = left_sensor;
  } else {
    Board_BeltStop(belt_id);
    return;
  }

  s_belt[belt_id].source_sensor = (target_sensor == right_sensor) ? left_sensor : right_sensor;
  s_belt[belt_id].target_sensor = target_sensor;

  run_belt_towards_sensor(belt_id, target_sensor);
  s_belt[belt_id].mode = MODE_PHYSICAL_MOVING;
}

static void tick_physical_moving(uint8_t belt_id)
{
  uint8_t target_sensor;

  if (!belt_id_valid(belt_id)) {
    return;
  }

  target_sensor = s_belt[belt_id].target_sensor;
  if (target_sensor == 0U) {
    s_belt[belt_id].mode = MODE_PHYSICAL_ARMED;
    Board_BeltStop(belt_id);
    return;
  }

  run_belt_towards_sensor(belt_id, target_sensor);

  /*
     Toi cam bien doi dien thi HOLD bang ca 2 relay cua bang tai do,
     giong logic cu:
     - Belt 1: PA11 + PA12
     - Belt 2: PA15 + PB3
  */
  if (sensor_active_by_id(target_sensor)) {
    Board_BeltHold(belt_id);
    s_belt[belt_id].mode = MODE_PHYSICAL_HOLD;
  }
}

static void tick_physical_hold(uint8_t belt_id)
{
  uint8_t target_sensor;

  if (!belt_id_valid(belt_id)) {
    return;
  }

  target_sensor = s_belt[belt_id].target_sensor;
  if (target_sensor == 0U) {
    s_belt[belt_id].mode = MODE_PHYSICAL_ARMED;
    Board_BeltStop(belt_id);
    return;
  }

  /*
     Con hang tai cam bien dich thi tiep tuc HOLD,
     khong cho nhay chieu nguoc.
  */
  if (sensor_active_by_id(target_sensor)) {
    Board_BeltHold(belt_id);
    return;
  }

  /*
     Khi lay hang ra/mat tin hieu cam bien dich:
     - Tat relay cua bang tai do.
     - Quay lai che do chờ chu ky moi.
  */
  Board_BeltStop(belt_id);
  s_belt[belt_id].source_sensor = 0U;
  s_belt[belt_id].target_sensor = 0U;
  s_belt[belt_id].mode = MODE_PHYSICAL_ARMED;
}

void Belt_Tick(void)
{
  uint8_t i;

  if (s_state == SYS_ESTOP) {
    Board_RelayAllOff();
    return;
  }

  if (s_stop_locked) {
    Board_RelayAllOff();
    return;
  }

  for (i = 1U; i <= MAX_BELTS; i++) {
    switch (s_belt[i].mode) {
    case MODE_LOAD_ARMED:
      tick_load_armed(i);
      break;

    case MODE_LOAD_MOVING:
      tick_load_moving(i);
      break;

    case MODE_UNLOAD_MOVING:
      tick_unload_moving(i);
      break;

    case MODE_PHYSICAL_ARMED:
      tick_physical_armed(i);
      break;

    case MODE_PHYSICAL_MOVING:
      tick_physical_moving(i);
      break;

    case MODE_PHYSICAL_HOLD:
      tick_physical_hold(i);
      break;

    case MODE_IDLE:
    default:
      break;
    }
  }

  refresh_system_state();
}



