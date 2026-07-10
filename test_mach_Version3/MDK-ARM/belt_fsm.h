#ifndef BELT_FSM_H
#define BELT_FSM_H

#include "board_gpio.h"
#include <stdint.h>

#define ESTOP_SRC_NONE     0U
#define ESTOP_SRC_EMER     10U
#define ESTOP_SRC_BUMPER1  11U
#define ESTOP_SRC_BUMPER2  12U

#define BELT_SEQ_NONE      0UL

typedef enum {
  BELT_CMD_OK = 0,
  BELT_CMD_BUSY,
  BELT_CMD_ESTOP,
  BELT_CMD_INVALID,
  BELT_CMD_NO_CARGO,
  BELT_CMD_STOP_LOCK,
  BELT_CMD_FAULT,
  BELT_CMD_COMM_LOST,
  BELT_CMD_NOT_READY
} BeltCmdResult_t;

typedef enum {
  BELT_PUBLIC_IDLE = 0,
  BELT_PUBLIC_LOAD_ARMED,
  BELT_PUBLIC_LOADING,
  BELT_PUBLIC_LOADED,
  BELT_PUBLIC_UNLOADING,
  BELT_PUBLIC_MANUAL,
  BELT_PUBLIC_HOLD,
  BELT_PUBLIC_FAULT
} BeltPublicState_t;

typedef enum {
  BELT_FAULT_NONE = 0,
  BELT_FAULT_LOAD_TIMEOUT,
  BELT_FAULT_LOAD_MOVE_TIMEOUT,
  BELT_FAULT_UNLOAD_TIMEOUT,
  BELT_FAULT_JAM,
  BELT_FAULT_BAD_SENSOR,
  BELT_FAULT_COMM_LOST,
  BELT_FAULT_MANUAL_TIMEOUT
} BeltFaultCode_t;

typedef enum {
  BELT_EVENT_NONE = 0,
  BELT_EVENT_LOAD_DETECTED,    /* EVENT LOAD_DETECTED,belt,source_sensor,target_sensor */
  BELT_EVENT_LOAD_DONE,        /* EVENT LOAD_DONE,belt,cargo_sensor */
  BELT_EVENT_UNLOAD_DONE,      /* EVENT UNLOAD_DONE,belt,side,exit_sensor */
  BELT_EVENT_MANUAL_RUN,       /* EVENT MANUAL_RUN,belt,side */
  BELT_EVENT_MANUAL_STOP,      /* EVENT MANUAL_STOP,belt */
  BELT_EVENT_FAULT             /* EVENT FAULT */
} BeltEventType_t;

typedef struct {
  BeltEventType_t type;
  uint8_t belt_id;
  uint32_t seq;
  BeltSide_t side;
  BeltFaultCode_t fault;
  uint8_t sensor_a;             /* source / cargo / exit sensor depending on event */
  uint8_t sensor_b;             /* target sensor for LOAD_DETECTED */
} BeltEvent_t;

void Belt_Init(void);
void Belt_Tick(void);

SystemState_t Belt_GetState(void);
uint8_t Belt_GetActiveBelt(void);       /* bitmask: 1=belt1, 2=belt2, 3=both */
BeltDirection_t Belt_GetDirection(void);
uint8_t Belt_GetEstopSource(void);
uint8_t Belt_HasCargo(uint8_t belt_id);
uint8_t Belt_IsStopLocked(void);
uint8_t Belt_GetFaultCode(void);
BeltPublicState_t Belt_GetBeltPublicState(uint8_t belt_id);
const char *Belt_StateToString(SystemState_t st);
const char *Belt_PublicStateToString(BeltPublicState_t st);
const char *Belt_FaultToString(BeltFaultCode_t fault);

/* ROS2/Web commands. seq = 0 if the old protocol has no sequence id. */
BeltCmdResult_t Belt_CmdStartLoad(uint8_t belt_id);
BeltCmdResult_t Belt_CmdStartLoadSeq(uint8_t belt_id, uint32_t seq);
BeltCmdResult_t Belt_CmdUnload(uint8_t belt_id, BeltSide_t side);
BeltCmdResult_t Belt_CmdUnloadSeq(uint8_t belt_id, BeltSide_t side, uint32_t seq);
BeltCmdResult_t Belt_CmdManualRunSeq(uint8_t belt_id, BeltSide_t side, uint32_t seq);
BeltCmdResult_t Belt_CmdManualStopSeq(uint8_t belt_id, uint32_t seq);

/* Physical buttons / safety */
void Belt_TriggerEstop(uint8_t source_code);
void Belt_OnStopButton(void);
uint8_t Belt_OnStartButton(void);   /* 1 = READY enabled, 0 = ignored */

/*
   return 0 = nothing
   return 1 = ESTOP reset OK
   return 2 = STOP_LOCK cleared
   return 3 = FAULT cleared
   return 4 = COMM_LOST cleared
*/
uint8_t Belt_OnResetButton(void);
uint8_t Belt_TryResetEstop(void);

/* Communication supervision */
uint8_t Belt_SetCommLost(void);      /* 1 if state changed to COMM_LOST */
uint8_t Belt_OnHeartbeatOk(void);    /* 1 if COMM_LOST was cleared */

uint8_t Belt_PopEvent(BeltEvent_t *ev);
uint8_t Belt_SensorAudioEnabled(void);

#endif
