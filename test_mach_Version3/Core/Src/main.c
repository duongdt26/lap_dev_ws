/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : AMR conveyor ? UART protocol + belt control
  *
  * Copy v?o project Keil c?ng c?c file trong inc/ v? src/.
  * Include path: th?m thu m?c inc/ c?a stm32_cvy.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "main.h"
#include "app_main.h"
#include "board_gpio.h"
#include "uart_proto.h"
/* Private variables ---------------------------------------------------------*/
UART_HandleTypeDef huart1;

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART1_UART_Init(void);

/**
  * @brief  Application entry point.
  */
int main(void)
{
  HAL_Init();
  SystemClock_Config();
  MX_GPIO_Init();
  MX_USART1_UART_Init();

  App_Init(&huart1);

  while (1)
  {
    App_Loop();
  }
}

/**
  * @brief System Clock Configuration ? HSI 8 MHz
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                              | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief USART1 ? PA9 TX, PA10 RX, 256000 8N1
  */
static void MX_USART1_UART_Init(void)
{
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 256000;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
	HAL_NVIC_SetPriority(USART1_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(USART1_IRQn);
}

/**
  * @brief GPIO ? sensors, relay, audio, buttons
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_AFIO_CLK_ENABLE();

  /* PA15 va PB3 dung lam GPIO relay, tat JTAG va giu SWD */
  __HAL_AFIO_REMAP_SWJ_NOJTAG();

  /* Relay + audio OFF */
  HAL_GPIO_WritePin(GPIOB, N1_Pin | N2_Pin | N3_Pin | N4_Pin | RF2_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, RUN1_Pin | RF1_Pin | RUN2_Pin, GPIO_PIN_RESET);

  /* PA0-PA5 sensors ? INPUT_PULLUP, active LOW (S5/S6 t? board_gpio.h) */
  GPIO_InitStruct.Pin = S1_Pin | S2_Pin | S3_Pin | S4_Pin | S5_PIN | S6_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* PB3 relay M2 + PB12-PB15 audio */
  GPIO_InitStruct.Pin = RF2_Pin | N1_Pin | N2_Pin | N3_Pin | N4_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* PA11/PA12/PA15 relay M1/M2 */
  GPIO_InitStruct.Pin = RUN1_Pin | RF1_Pin | RUN2_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* PB4 EMER, PB8/PB9 bumper ? active LOW (polling, no EXTI) */
  GPIO_InitStruct.Pin = Button_EMER_Pin | Bumper_S1_Pin | Bumper_S2_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* PB6/PB7 START/RESET - INPUT_PULLUP, active LOW */
  GPIO_InitStruct.Pin = Button_START_Pin | Button_RESET_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* PB5 STOP - INPUT_PULLUP, active LOW */
  GPIO_InitStruct.Pin = Button_STOP_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(Button_STOP_GPIO_Port, &GPIO_InitStruct);
}

/**
  * @brief  Error handler
  */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  UART_Proto_RxCpltCallback(huart);
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
  UART_Proto_ErrorCallback(huart);
}
void Error_Handler(void)
{
  __disable_irq();
  Board_RelayAllOff();
  while (1)
  {
  }
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
  (void)file;
  (void)line;
}
#endif
