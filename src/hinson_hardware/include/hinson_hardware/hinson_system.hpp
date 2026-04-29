#ifndef HINSON_HARDWARE__HINSON_SYSTEM_HPP_
#define HINSON_HARDWARE__HINSON_SYSTEM_HPP_

#include <memory>
#include <string>
#include <vector>

#include "hardware_interface/handle.hpp"
#include "hardware_interface/hardware_info.hpp"
#include "hardware_interface/system_interface.hpp"
#include "hardware_interface/types/hardware_interface_return_values.hpp"
#include "rclcpp/macros.hpp"
#include "rclcpp_lifecycle/state.hpp"

// Forward declaration cho libmodbus để tránh include trực tiếp trong header
struct _modbus;
typedef struct _modbus modbus_t;

namespace hinson_hardware
{
class HinsonSystemHardware : public hardware_interface::SystemInterface
{
public:
  RCLCPP_SHARED_PTR_DEFINITIONS(HinsonSystemHardware)

  hardware_interface::CallbackReturn on_init(
    const hardware_interface::HardwareInfo & info) override;

  std::vector<hardware_interface::StateInterface> export_state_interfaces() override;

  std::vector<hardware_interface::CommandInterface> export_command_interfaces() override;

  hardware_interface::CallbackReturn on_activate(
    const rclcpp_lifecycle::State & previous_state) override;

  hardware_interface::CallbackReturn on_deactivate(
    const rclcpp_lifecycle::State & previous_state) override;

  hardware_interface::return_type read(
    const rclcpp::Time & time, const rclcpp::Duration & period) override;

  hardware_interface::return_type write(
    const rclcpp::Time & time, const rclcpp::Duration & period) override;

private:
  // Thông số giao tiếp
  std::string port_;
  int baudrate_;
  modbus_t * ctx_ = nullptr;

  // Mảng lưu dữ liệu (2 bánh: 0 là trái, 1 là phải)
  std::vector<double> hw_commands_;
  std::vector<double> hw_positions_;
  std::vector<double> hw_velocities_;
  
  // Biến phục vụ cộng dồn xung Hall (tránh overflow của thanh ghi 16 bit)
  std::vector<uint16_t> prev_hall_counts_;
};

}  // namespace hinson_hardware

#endif  // HINSON_HARDWARE__HINSON_SYSTEM_HPP_

// chuong duong