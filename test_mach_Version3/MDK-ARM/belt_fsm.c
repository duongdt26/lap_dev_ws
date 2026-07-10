#include "belt_fsm.h"
#include "board_gpio.h"
#include <string.h>

/*
  AMR conveyor FSM — refactor for Nav2/Web + physical safety buttons

  Main policy:
  - EMER/BUMPER has highest priority: stop all relay immediately and enter ESTOP.
  - STOP physical = STOP_LOCK. It stops all conveyor jobs and rejects ROS2 commands.
  - RESET only clears ESTOP/STOP_LOCK/FAULT/COMM_LOST. RESET never starts a belt.
  - START physical only enables READY. START never runs a conveyor by itself.
  - ROS2/Web can run conveyor only when system is READY/RUNNING and no fault/estop/stop lock.
  - Each conveyor has independent state + timeout to prevent endless motor run.
*/

typedef enum {
  MODE_IDLE = 0,
  MODE_LOAD_ARMED,
  MODE_LOAD_MOVING,
  MODE_UNLOAD_MOVING,
  MODE_MANUAL_MOVING,
  MODE_FAULT
} BeltMode_t;

typedef struct {
  BeltMode_t mode;
  uint8_t source_sensor;      /* 1..4 */
  uint8_t target_sensor;      /* 1..4 */
  uint8_t exit_sensor;        /* 1..4 */
  uint8_t exit_seen;
  uint8_t cargo_valid;
  uint8_t cargo_sensor;
  BeltDirection_t dir;
  BeltSide_t unload_side;
  BeltSide_t manual_side;
  uint32_t seq;
  uint32_t state_enter_tick;
  BeltFaultCode_t fault;
} BeltRuntime_t;

typedef struct {
  uint8_t raw_last;
  uint8_t stable;
  uint32_t last_change_tick;
} SensorFilter_t;

#define MAX_BELTS                 2U
#define EVENT_Q_SIZE              12U
#define SENSOR_COUNT              6U
#define SENSOR_FILTER_MS          30U
#define LOAD_ARM_TIMEOUT_MS       5000U
#define LOAD_MOVE_TIMEOUT_MS      8000U
#define UNLOAD_MOVE_TIMEOUT_MS    8000U
#define MANUAL_RUN_TIMEOUT_MS     15000U

static SystemState_t s_state = SYS_BOOT;
static uint8_t s_estop_source = ESTOP_SRC_NONE;
static uint8_t s_stop_locked = 0U;
static BeltFaultCode_t s_global_fault = BELT_FAULT_NONE;
static BeltRuntime_t s_belt[MAX_BELTS + 1U]; /* index 1..2 */
static SensorFilter_t s_sensor[SENSOR_COUNT + 1U]; /* index 1..6 */
static BeltEvent_t s_evt_q[EVENT_Q_SIZE];
static uint8_t s_evt_head = 0U;
static uint8_t s_evt_tail = 0U;

/* ================= EVENT QUEUE ================= */

static void push_event(BeltEventType_t type, uint8_t belt_id, uint32_t seq,
                       BeltSide_t side, BeltFaultCode_t fault,
                       uint8_t sensor_a, uint8_t sensor_b)
{
  uint8_t next = (uint8_t)((s_evt_head + 1U) % EVENT_Q_SIZE);

  if (next == s_evt_tail) {
    s_evt_tail = (uint8_t)((s_evt_tail + 1U) % EVENT_Q_SIZE);
  }

  s_evt_q[s_evt_head].type = type;
  s_evt_q[s_evt_head].belt_id = belt_id;
  s_evt_q[s_evt_head].seq = seq;
  s_evt_q[s_evt_head].side = side;
  s_evt_q[s_evt_head].fault = fault;
  s_evt_q[s_evt_head].sensor_a = sensor_a;
  s_evt_q[s_evt_head].sensor_b = sensor_b;
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

/* ================= SENSOR FILTERS ================= */

static uint8_t read_sensor_raw_by_id(uint8_t sensor_id)
{
  switch (sensor_id) {
  case 1U: return Board_S1();
  case 2U: return Board_S2();
  case 3U: return Board_S3();
  case 4U: return Board_S4();
  case 5U: return Board_S5();
  case 6U: return Board_S6();
  default: return 0U;
  }
}

static void sensor_filter_init_one(uint8_t sensor_id)
{
  uint8_t raw;

  if (sensor_id == 0U || sensor_id > SENSOR_COUNT) {
    return;
  }

  raw = read_sensor_raw_by_id(sensor_id);
  s_sensor[sensor_id].raw_last = raw;
  s_sensor[sensor_id].stable = raw;
  s_sensor[sensor_id].last_change_tick = HAL_GetTick();
}

static void sensor_filters_init(void)
{
  uint8_t i;

  for (i = 1U; i <= SENSOR_COUNT; i++) {
    sensor_filter_init_one(i);
  }
}

static void sensor_filters_tick(void)
{
  uint8_t i;
  uint8_t raw;

  for (i = 1U; i <= SENSOR_COUNT; i++) {
    raw = read_sensor_raw_by_id(i);

    if (raw != s_sensor[i].raw_last) {
      s_sensor[i].raw_last = raw;
      s_sensor[i].last_change_tick = HAL_GetTick();
    }

    if ((HAL_GetTick() - s_sensor[i].last_change_tick) >= SENSOR_FILTER_MS) {
      s_sensor[i].stable = s_sensor[i].raw_last;
    }
  }
}

static uint8_t sensor_active_by_id(uint8_t sensor_id)
{
  if (sensor_id == 0U || sensor_id > SENSOR_COUNT) {
    return 0U;
  }

  return s_sensor[sensor_id].stable ? 1U : 0U;
}

/* ================= HELPERS ================= */

static uint8_t belt_id_valid(uint8_t belt_id)
{
  return (belt_id >= 1U && belt_id <= MAX_BELTS) ? 1U : 0U;
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
    if (sensor_active_by_id(1U)) { return 1U; }
    if (sensor_active_by_id(3U)) { return 3U; }
  } else if (belt_id == 2U) {
    if (sensor_active_by_id(2U)) { return 2U; }
    if (sensor_active_by_id(4U)) { return 4U; }
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
  if (target_sensor == 3U || target_sensor == 4U) {
    return BELT_DIR_LEFT;
  }

  return BELT_DIR_RIGHT;
}

static void enter_mode(uint8_t belt_id, BeltMode_t mode)
{
  if (!belt_id_valid(belt_id)) {
    return;
  }

  s_belt[belt_id].mode = mode;
  s_belt[belt_id].state_enter_tick = HAL_GetTick();
}

static void stop_and_clear_runtime(uint8_t belt_id)
{
  if (!belt_id_valid(belt_id)) {
    return;
  }

  Board_BeltStop(belt_id);
  s_belt[belt_id].mode = MODE_IDLE;
  s_belt[belt_id].source_sensor = 0U;
  s_belt[belt_id].target_sensor = 0U;
  s_belt[belt_id].exit_sensor = 0U;
  s_belt[belt_id].exit_seen = 0U;
  s_belt[belt_id].seq = BELT_SEQ_NONE;
  s_belt[belt_id].dir = BELT_DIR_LEFT;
  s_belt[belt_id].unload_side = BELT_SIDE_LEFT;
  s_belt[belt_id].manual_side = BELT_SIDE_LEFT;
  s_belt[belt_id].state_enter_tick = HAL_GetTick();
  s_belt[belt_id].fault = BELT_FAULT_NONE;
}

static uint8_t any_belt_active(void)
{
  uint8_t i;

  for (i = 1U; i <= MAX_BELTS; i++) {
    if (s_belt[i].mode == MODE_LOAD_ARMED ||
        s_belt[i].mode == MODE_LOAD_MOVING ||
        s_belt[i].mode == MODE_UNLOAD_MOVING ||
        s_belt[i].mode == MODE_MANUAL_MOVING) {
      return 1U;
    }
  }

  return 0U;
}

static uint8_t any_belt_fault(void)
{
  uint8_t i;

  for (i = 1U; i <= MAX_BELTS; i++) {
    if (s_belt[i].mode == MODE_FAULT || s_belt[i].fault != BELT_FAULT_NONE) {
      return 1U;
    }
  }

  return 0U;
}

static void refresh_system_state(void)
{
  if (s_state == SYS_ESTOP || s_state == SYS_COMM_LOST) {
    return;
  }

  if (s_stop_locked) {
    s_state = SYS_STOP_LOCK;
    return;
  }

  if (any_belt_fault() || s_global_fault != BELT_FAULT_NONE) {
    s_state = SYS_FAULT;
    return;
  }

  if (any_belt_active()) {
    s_state = SYS_RUNNING;
    return;
  }

  if (s_state == SYS_READY || s_state == SYS_RUNNING) {
    s_state = SYS_READY;
  } else {
    s_state = SYS_IDLE;
  }
}

static BeltDirection_t direction_from_side(BeltSide_t side)
{
  return (side == BELT_SIDE_LEFT) ? BELT_DIR_LEFT : BELT_DIR_RIGHT;
}

static void run_belt_towards_sensor(uint8_t belt_id, uint8_t sensor_id)
{
  BeltDirection_t dir;

  if (!belt_id_valid(belt_id)) {
    return;
  }

  dir = direction_towards_sensor(sensor_id);
  s_belt[belt_id].dir = dir;
  Board_BeltRun(belt_id, dir);
}

static void run_belt_manual(uint8_t belt_id, BeltSide_t side)
{
  BeltDirection_t dir;

  if (!belt_id_valid(belt_id)) {
    return;
  }

  dir = direction_from_side(side);
  s_belt[belt_id].dir = dir;
  s_belt[belt_id].manual_side = side;
  Board_BeltRun(belt_id, dir);
}

static void set_belt_fault(uint8_t belt_id, BeltFaultCode_t fault)
{
  if (!belt_id_valid(belt_id)) {
    return;
  }

  Board_BeltStop(belt_id);
  s_belt[belt_id].fault = fault;
  s_global_fault = fault;
  enter_mode(belt_id, MODE_FAULT);
  s_state = SYS_FAULT;
  push_event(BELT_EVENT_FAULT, belt_id, s_belt[belt_id].seq, BELT_SIDE_LEFT, fault, 0U, 0U);
}

static void clear_all_belt_faults(void)
{
  uint8_t i;

  for (i = 1U; i <= MAX_BELTS; i++) {
    s_belt[i].fault = BELT_FAULT_NONE;
    if (s_belt[i].mode == MODE_FAULT) {
      stop_and_clear_runtime(i);
    }
  }

  s_global_fault = BELT_FAULT_NONE;
}

static uint8_t command_blocked_result(void)
{
  if (s_state == SYS_ESTOP) {
    return BELT_CMD_ESTOP;
  }

  if (s_state == SYS_COMM_LOST) {
    return BELT_CMD_COMM_LOST;
  }

  if (s_stop_locked || s_state == SYS_STOP_LOCK) {
    return BELT_CMD_STOP_LOCK;
  }

  if (s_state == SYS_FAULT || any_belt_fault()) {
    return BELT_CMD_FAULT;
  }

  if (s_state != SYS_READY && s_state != SYS_RUNNING) {
    return BELT_CMD_NOT_READY;
  }

  return BELT_CMD_OK;
}

/* ================= PUBLIC INFO ================= */

void Belt_Init(void)
{
  uint8_t i;

  s_state = SYS_IDLE;
  s_estop_source = ESTOP_SRC_NONE;
  s_stop_locked = 0U;
  s_global_fault = BELT_FAULT_NONE;

  for (i = 1U; i <= MAX_BELTS; i++) {
    memset(&s_belt[i], 0, sizeof(s_belt[i]));
    s_belt[i].mode = MODE_IDLE;
    s_belt[i].dir = BELT_DIR_LEFT;
    s_belt[i].unload_side = BELT_SIDE_LEFT;
    s_belt[i].state_enter_tick = HAL_GetTick();
  }

  s_evt_head = 0U;
  s_evt_tail = 0U;
  sensor_filters_init();
  Board_RelayAllOff();
}

SystemState_t Belt_GetState(void)
{
  return s_state;
}

uint8_t Belt_GetActiveBelt(void)
{
  uint8_t mask = 0U;

  if (s_belt[1U].mode == MODE_LOAD_ARMED ||
      s_belt[1U].mode == MODE_LOAD_MOVING ||
      s_belt[1U].mode == MODE_UNLOAD_MOVING ||
      s_belt[1U].mode == MODE_MANUAL_MOVING) {
    mask |= 1U;
  }

  if (s_belt[2U].mode == MODE_LOAD_ARMED ||
      s_belt[2U].mode == MODE_LOAD_MOVING ||
      s_belt[2U].mode == MODE_UNLOAD_MOVING ||
      s_belt[2U].mode == MODE_MANUAL_MOVING) {
    mask |= 2U;
  }

  return mask;
}

BeltDirection_t Belt_GetDirection(void)
{
  if (s_belt[1U].mode == MODE_LOAD_MOVING ||
      s_belt[1U].mode == MODE_UNLOAD_MOVING ||
      s_belt[1U].mode == MODE_MANUAL_MOVING) {
    return s_belt[1U].dir;
  }

  if (s_belt[2U].mode == MODE_LOAD_MOVING ||
      s_belt[2U].mode == MODE_UNLOAD_MOVING ||
      s_belt[2U].mode == MODE_MANUAL_MOVING) {
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
    /*
      Report physical cargo if either the FSM has a valid cargo latch
      or at least one cargo sensor on this belt is currently active.
      This keeps ROS2 synchronized after RESET/ESTOP while cargo is still
      physically sitting on the conveyor.
    */
    return (s_belt[belt_id].cargo_valid || first_active_sensor_on_belt(belt_id) != 0U) ? 1U : 0U;
  }

  return 0U;
}

uint8_t Belt_IsStopLocked(void)
{
  return s_stop_locked;
}

uint8_t Belt_GetFaultCode(void)
{
  return (uint8_t)s_global_fault;
}

BeltPublicState_t Belt_GetBeltPublicState(uint8_t belt_id)
{
  if (!belt_id_valid(belt_id)) {
    return BELT_PUBLIC_IDLE;
  }

  if (s_belt[belt_id].fault != BELT_FAULT_NONE || s_belt[belt_id].mode == MODE_FAULT) {
    return BELT_PUBLIC_FAULT;
  }

  switch (s_belt[belt_id].mode) {
  case MODE_LOAD_ARMED:    return BELT_PUBLIC_LOAD_ARMED;
  case MODE_LOAD_MOVING:   return BELT_PUBLIC_LOADING;
  case MODE_UNLOAD_MOVING: return BELT_PUBLIC_UNLOADING;
  case MODE_MANUAL_MOVING: return BELT_PUBLIC_MANUAL;
  case MODE_IDLE:
  default:
    return s_belt[belt_id].cargo_valid ? BELT_PUBLIC_LOADED : BELT_PUBLIC_IDLE;
  }
}

const char *Belt_StateToString(SystemState_t st)
{
  switch (st) {
  case SYS_BOOT:      return "BOOT";
  case SYS_IDLE:      return "IDLE";
  case SYS_READY:     return "READY";
  case SYS_RUNNING:   return "RUNNING";
  case SYS_STOP_LOCK: return "STOP_LOCK";
  case SYS_ESTOP:     return "ESTOP";
  case SYS_FAULT:     return "FAULT";
  case SYS_COMM_LOST: return "COMM_LOST";
  default:            return "UNKNOWN";
  }
}

const char *Belt_PublicStateToString(BeltPublicState_t st)
{
  switch (st) {
  case BELT_PUBLIC_LOAD_ARMED: return "LOAD_ARMED";
  case BELT_PUBLIC_LOADING:    return "LOADING";
  case BELT_PUBLIC_LOADED:     return "LOADED";
  case BELT_PUBLIC_UNLOADING:  return "UNLOADING";
  case BELT_PUBLIC_MANUAL:     return "MANUAL";
  case BELT_PUBLIC_HOLD:       return "HOLD";
  case BELT_PUBLIC_FAULT:      return "FAULT";
  case BELT_PUBLIC_IDLE:
  default:                     return "IDLE";
  }
}

const char *Belt_FaultToString(BeltFaultCode_t fault)
{
  switch (fault) {
  case BELT_FAULT_LOAD_TIMEOUT:      return "LOAD_TIMEOUT";
  case BELT_FAULT_LOAD_MOVE_TIMEOUT: return "LOAD_MOVE_TIMEOUT";
  case BELT_FAULT_UNLOAD_TIMEOUT:    return "UNLOAD_TIMEOUT";
  case BELT_FAULT_JAM:               return "JAM";
  case BELT_FAULT_BAD_SENSOR:        return "BAD_SENSOR";
  case BELT_FAULT_COMM_LOST:         return "COMM_LOST";
  case BELT_FAULT_MANUAL_TIMEOUT:    return "MANUAL_TIMEOUT";
  case BELT_FAULT_NONE:
  default:                           return "NONE";
  }
}

uint8_t Belt_SensorAudioEnabled(void)
{
  return 0U;
}

/* ================= SAFETY / PHYSICAL BUTTONS ================= */

void Belt_TriggerEstop(uint8_t source_code)
{
  uint8_t i;

  s_state = SYS_ESTOP;
  s_estop_source = source_code;
  s_stop_locked = 0U;

  for (i = 1U; i <= MAX_BELTS; i++) {
    stop_and_clear_runtime(i);
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

  if (HAL_GPIO_ReadPin(BUMPER1_PORT, BUMPER1_PIN) == BUMPER_ACTIVE) {
    return 0U;
  }

  if (HAL_GPIO_ReadPin(BUMPER2_PORT, BUMPER2_PIN) == BUMPER_ACTIVE) {
    return 0U;
  }

  s_state = SYS_IDLE;
  s_estop_source = ESTOP_SRC_NONE;
  s_stop_locked = 0U;
  s_global_fault = BELT_FAULT_NONE;

  for (i = 1U; i <= MAX_BELTS; i++) {
    stop_and_clear_runtime(i);
    s_belt[i].cargo_valid = 0U;
    s_belt[i].cargo_sensor = 0U;
  }

  Board_RelayAllOff();
  return 1U;
}

uint8_t Belt_OnResetButton(void)
{
  if (s_state == SYS_ESTOP) {
    return Belt_TryResetEstop() ? 1U : 0U;
  }

  if (s_stop_locked || s_state == SYS_STOP_LOCK) {
    s_stop_locked = 0U;
    Board_RelayAllOff();
    s_state = SYS_IDLE;
    return 2U;
  }

  if (s_state == SYS_FAULT || any_belt_fault()) {
    Board_RelayAllOff();
    clear_all_belt_faults();
    s_state = SYS_IDLE;
    return 3U;
  }

  if (s_state == SYS_COMM_LOST) {
    Board_RelayAllOff();
    s_global_fault = BELT_FAULT_NONE;
    s_state = SYS_IDLE;
    return 4U;
  }

  return 0U;
}

void Belt_OnStopButton(void)
{
  uint8_t i;

  Board_RelayAllOff();

  if (s_state == SYS_ESTOP) {
    return;
  }

  for (i = 1U; i <= MAX_BELTS; i++) {
    stop_and_clear_runtime(i);
  }

  s_stop_locked = 1U;
  s_state = SYS_STOP_LOCK;
}

uint8_t Belt_OnStartButton(void)
{
  if (s_state == SYS_ESTOP || s_state == SYS_FAULT || s_state == SYS_COMM_LOST) {
    return 0U;
  }

  if (s_stop_locked || s_state == SYS_STOP_LOCK) {
    s_stop_locked = 0U;
  }

  Board_RelayAllOff();
  refresh_system_state();

  if (s_state == SYS_IDLE || s_state == SYS_READY) {
    s_state = SYS_READY;
    return 1U;
  }

  return 0U;
}

uint8_t Belt_SetCommLost(void)
{
  uint8_t i;

  if (s_state == SYS_ESTOP || s_state == SYS_COMM_LOST) {
    if (s_state == SYS_COMM_LOST) {
      Board_RelayAllOff();
    }
    return 0U;
  }

  for (i = 1U; i <= MAX_BELTS; i++) {
    stop_and_clear_runtime(i);
  }

  Board_RelayAllOff();
  s_global_fault = BELT_FAULT_COMM_LOST;
  s_state = SYS_COMM_LOST;
  return 1U;
}

uint8_t Belt_OnHeartbeatOk(void)
{
  /*
    Heartbeat only proves that the UART link is alive again.
    It must not clear SYS_COMM_LOST by itself, otherwise $CMD,RESET can
    mark the link OK first and then report NOTHING_TO_RESET.
    COMM_LOST is cleared only by RESET / $CMD,RESET.
  */
  return 0U;
}

/* ================= ROS2 / WEB COMMANDS ================= */

BeltCmdResult_t Belt_CmdStartLoad(uint8_t belt_id)
{
  return Belt_CmdStartLoadSeq(belt_id, BELT_SEQ_NONE);
}

BeltCmdResult_t Belt_CmdStartLoadSeq(uint8_t belt_id, uint32_t seq)
{
  BeltCmdResult_t blocked;

  if (!belt_id_valid(belt_id)) {
    return BELT_CMD_INVALID;
  }

  blocked = (BeltCmdResult_t)command_blocked_result();
  if (blocked != BELT_CMD_OK) {
    return blocked;
  }

  if (s_belt[belt_id].mode != MODE_IDLE) {
    return BELT_CMD_BUSY;
  }

  stop_and_clear_runtime(belt_id);
  s_belt[belt_id].cargo_valid = 0U;
  s_belt[belt_id].cargo_sensor = 0U;
  s_belt[belt_id].seq = seq;
  s_belt[belt_id].source_sensor = 0U;
  s_belt[belt_id].target_sensor = 0U;
  s_belt[belt_id].exit_sensor = 0U;
  s_belt[belt_id].exit_seen = 0U;

  enter_mode(belt_id, MODE_LOAD_ARMED);
  s_state = SYS_RUNNING;
  Board_BeltStop(belt_id);
  return BELT_CMD_OK;
}

BeltCmdResult_t Belt_CmdUnload(uint8_t belt_id, BeltSide_t side)
{
  return Belt_CmdUnloadSeq(belt_id, side, BELT_SEQ_NONE);
}

BeltCmdResult_t Belt_CmdUnloadSeq(uint8_t belt_id, BeltSide_t side, uint32_t seq)
{
  uint8_t sensor_id;
  uint8_t exit_sensor;
  BeltCmdResult_t blocked;

  if (!belt_id_valid(belt_id)) {
    return BELT_CMD_INVALID;
  }

  blocked = (BeltCmdResult_t)command_blocked_result();
  if (blocked != BELT_CMD_OK) {
    return blocked;
  }

  if (s_belt[belt_id].mode != MODE_IDLE) {
    return BELT_CMD_BUSY;
  }

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

  s_belt[belt_id].seq = seq;
  s_belt[belt_id].unload_side = side;
  s_belt[belt_id].source_sensor = sensor_id;
  s_belt[belt_id].target_sensor = 0U;
  s_belt[belt_id].exit_sensor = exit_sensor;
  s_belt[belt_id].exit_seen = sensor_active_by_id(exit_sensor);

  enter_mode(belt_id, MODE_UNLOAD_MOVING);
  s_state = SYS_RUNNING;
  run_belt_towards_sensor(belt_id, exit_sensor);
  return BELT_CMD_OK;
}


BeltCmdResult_t Belt_CmdManualRunSeq(uint8_t belt_id, BeltSide_t side, uint32_t seq)
{
  BeltCmdResult_t blocked;

  if (!belt_id_valid(belt_id)) {
    return BELT_CMD_INVALID;
  }

  blocked = (BeltCmdResult_t)command_blocked_result();
  if (blocked != BELT_CMD_OK) {
    return blocked;
  }

  if (s_belt[belt_id].mode != MODE_IDLE) {
    return BELT_CMD_BUSY;
  }

  /* Manual run is only for ROS2 maintenance/test command.
     It does not latch/clear cargo state and it is never triggered by physical START. */
  stop_and_clear_runtime(belt_id);
  s_belt[belt_id].seq = seq;
  s_belt[belt_id].manual_side = side;

  enter_mode(belt_id, MODE_MANUAL_MOVING);
  s_state = SYS_RUNNING;
  run_belt_manual(belt_id, side);
  push_event(BELT_EVENT_MANUAL_RUN, belt_id, seq, side, BELT_FAULT_NONE, 0U, 0U);
  return BELT_CMD_OK;
}

BeltCmdResult_t Belt_CmdManualStopSeq(uint8_t belt_id, uint32_t seq)
{
  if (!belt_id_valid(belt_id)) {
    return BELT_CMD_INVALID;
  }

  if (s_state == SYS_ESTOP) {
    return BELT_CMD_ESTOP;
  }

  if (s_state == SYS_COMM_LOST) {
    return BELT_CMD_COMM_LOST;
  }

  if (s_stop_locked || s_state == SYS_STOP_LOCK) {
    return BELT_CMD_STOP_LOCK;
  }

  if (s_belt[belt_id].mode != MODE_MANUAL_MOVING) {
    return BELT_CMD_INVALID;
  }

  Board_BeltStop(belt_id);
  enter_mode(belt_id, MODE_IDLE);
  s_belt[belt_id].seq = BELT_SEQ_NONE;
  push_event(BELT_EVENT_MANUAL_STOP, belt_id, seq, BELT_SIDE_LEFT, BELT_FAULT_NONE, 0U, 0U);
  refresh_system_state();
  return BELT_CMD_OK;
}

/* ================= TICK HANDLERS ================= */

static void tick_load_armed(uint8_t belt_id)
{
  uint8_t sensor_id;
  uint8_t target_sensor;

  if ((HAL_GetTick() - s_belt[belt_id].state_enter_tick) > LOAD_ARM_TIMEOUT_MS) {
    set_belt_fault(belt_id, BELT_FAULT_LOAD_TIMEOUT);
    return;
  }

  sensor_id = first_active_sensor_on_belt(belt_id);
  if (sensor_id == 0U) {
    Board_BeltStop(belt_id);
    return;
  }

  target_sensor = opposite_sensor(sensor_id);
  if (target_sensor == 0U || sensor_to_belt(target_sensor) != belt_id) {
    set_belt_fault(belt_id, BELT_FAULT_BAD_SENSOR);
    return;
  }

  s_belt[belt_id].source_sensor = sensor_id;
  s_belt[belt_id].target_sensor = target_sensor;
  push_event(BELT_EVENT_LOAD_DETECTED, belt_id, s_belt[belt_id].seq, BELT_SIDE_LEFT, BELT_FAULT_NONE, sensor_id, target_sensor);

  run_belt_towards_sensor(belt_id, target_sensor);
  enter_mode(belt_id, MODE_LOAD_MOVING);
}

static void tick_load_moving(uint8_t belt_id)
{
  uint8_t target_sensor = s_belt[belt_id].target_sensor;

  if (target_sensor == 0U) {
    set_belt_fault(belt_id, BELT_FAULT_BAD_SENSOR);
    return;
  }

  if ((HAL_GetTick() - s_belt[belt_id].state_enter_tick) > LOAD_MOVE_TIMEOUT_MS) {
    set_belt_fault(belt_id, BELT_FAULT_LOAD_MOVE_TIMEOUT);
    return;
  }

  if (sensor_active_by_id(target_sensor)) {
    Board_BeltStop(belt_id);
    s_belt[belt_id].cargo_valid = 1U;
    s_belt[belt_id].cargo_sensor = target_sensor;
    push_event(BELT_EVENT_LOAD_DONE, belt_id, s_belt[belt_id].seq, BELT_SIDE_LEFT, BELT_FAULT_NONE, target_sensor, 0U);
    enter_mode(belt_id, MODE_IDLE);
    s_belt[belt_id].source_sensor = 0U;
    s_belt[belt_id].target_sensor = 0U;
    s_belt[belt_id].seq = BELT_SEQ_NONE;
  }
}

static void tick_unload_moving(uint8_t belt_id)
{
  uint8_t exit_sensor = s_belt[belt_id].exit_sensor;

  if (exit_sensor == 0U) {
    set_belt_fault(belt_id, BELT_FAULT_BAD_SENSOR);
    return;
  }

  if ((HAL_GetTick() - s_belt[belt_id].state_enter_tick) > UNLOAD_MOVE_TIMEOUT_MS) {
    set_belt_fault(belt_id, BELT_FAULT_UNLOAD_TIMEOUT);
    return;
  }

  if (s_belt[belt_id].exit_seen == 0U) {
    if (sensor_active_by_id(exit_sensor)) {
      s_belt[belt_id].exit_seen = 1U;
    }
    return;
  }

  if (!sensor_active_by_id(exit_sensor)) {
    Board_BeltStop(belt_id);
    s_belt[belt_id].cargo_valid = 0U;
    s_belt[belt_id].cargo_sensor = 0U;
    push_event(BELT_EVENT_UNLOAD_DONE, belt_id, s_belt[belt_id].seq, s_belt[belt_id].unload_side, BELT_FAULT_NONE, exit_sensor, 0U);
    enter_mode(belt_id, MODE_IDLE);
    s_belt[belt_id].source_sensor = 0U;
    s_belt[belt_id].target_sensor = 0U;
    s_belt[belt_id].exit_sensor = 0U;
    s_belt[belt_id].exit_seen = 0U;
    s_belt[belt_id].seq = BELT_SEQ_NONE;
  }
}

static void tick_manual_moving(uint8_t belt_id)
{
  if ((HAL_GetTick() - s_belt[belt_id].state_enter_tick) > MANUAL_RUN_TIMEOUT_MS) {
    set_belt_fault(belt_id, BELT_FAULT_MANUAL_TIMEOUT);
  }
}

void Belt_Tick(void)
{
  uint8_t i;

  sensor_filters_tick();

  if (s_state == SYS_ESTOP || s_state == SYS_STOP_LOCK || s_state == SYS_COMM_LOST) {
    Board_RelayAllOff();
    return;
  }

  if (s_stop_locked) {
    Board_RelayAllOff();
    s_state = SYS_STOP_LOCK;
    return;
  }

  if (s_state == SYS_FAULT) {
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

    case MODE_MANUAL_MOVING:
      tick_manual_moving(i);
      break;

    case MODE_FAULT:
      Board_BeltStop(i);
      break;

    case MODE_IDLE:
    default:
      break;
    }
  }

  refresh_system_state();
}
