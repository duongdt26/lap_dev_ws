// #include "hinson_hardware/hinson_system.hpp"
// #include <modbus/modbus.h>
// #include <rclcpp/rclcpp.hpp>

// namespace hinson_hardware
// {
//     // declare modbus's pointer
//     modbus_t *ctx_ = nullptr;

//     hardware_interface::CallbackReturn HinsonSystemHardware::on_init(
//         const hardware_interface::HardwareInfo & info)
//         {
//             if (hardware_interface::SystemInterface::on_init(info) !=
//                 hardware_interface::CallbackReturn::SUCCESS)
//             return hardware_interface::CallbackReturn::ERROR;

//              // Read param from URDF
//             port_ = info_.hardware_parameters["port"];
//             baudrate_ = std::stoi(info_.hardware_parameters["baudrate"]);

//             return hardware_interface::CallbackReturn::SUCCESS;
//         }

//     hardware_interface::CallbackReturn HinsonSystemHardware::on_activate(
//         const rclcpp_lifecycle::State & /*previous_state*/)
//         {
//         RCLCPP_INFO(rclcpp::get_logger("HinsonSystemHardware"), "Connecting to Modbus at %s...", port_.c_str());

//         // Khởi tạo Modbus RTU
//         ctx_ = modbus_new_rtu(port_.c_str(), baudrate_, 'N', 8, 1);
//         if (ctx_ == nullptr) {
//             RCLCPP_ERROR(rclcpp::get_logger("HinsonSystemHardware"), "Unable to create libmodbus context");
//             return hardware_interface::CallbackReturn::ERROR;
//         }

//         // Tùy chỉnh ID slave (giả sử ID = 10 như trong file Python cũ của cậu)
//         modbus_set_slave(ctx_, 10);
        
//         // Mở kết nối
//         if (modbus_connect(ctx_) == -1) {
//             RCLCPP_ERROR(rclcpp::get_logger("HinsonSystemHardware"), "Connection failed: %s", modbus_strerror(errno));
//             modbus_free(ctx_);
//             return hardware_interface::CallbackReturn::ERROR;
//         }

//         // --- CHUỖI LỆNH KHỞI ĐỘNG (Gỡ lỗi & Kích hoạt) ---
//         uint16_t clear_fault_1[1] = {1};
//         uint16_t clear_fault_0[1] = {0};
//         uint16_t individual_mode[1] = {1};
//         uint16_t enable_motor[2] = {1, 1}; // 2002 và 2003

//         modbus_write_registers(ctx_, 2000, 1, clear_fault_1);
//         rclcpp::sleep_for(std::chrono::milliseconds(100));
        
//         modbus_write_registers(ctx_, 2000, 1, clear_fault_0);
//         rclcpp::sleep_for(std::chrono::milliseconds(100));
        
//         modbus_write_registers(ctx_, 2001, 1, individual_mode);
//         modbus_write_registers(ctx_, 2002, 2, enable_motor);

//         RCLCPP_INFO(rclcpp::get_logger("HinsonSystemHardware"), "Driver Activated & Faults Cleared.");
//         return hardware_interface::CallbackReturn::SUCCESS;
//         }

//         hardware_interface::return_type HinsonSystemHardware::write(
//         const rclcpp::Time & /*time*/, const rclcpp::Duration & /*period*/)
//         {
//         // Tính toán lệnh RPM từ radian/s
//         // cmd_[0] là bánh trái, cmd_[1] là bánh phải (đã lấy từ command_interface)
        
//         int rpm_left = (cmd_[0] * 60.0 / (2.0 * M_PI)) * 30.0;
//         int rpm_right = (cmd_[1] * 60.0 / (2.0 * M_PI)) * 30.0;

//         // Giả sử thanh ghi 2006 là bánh trái, 2007 là bánh phải
//         uint16_t speed_cmds[2];
//         speed_cmds[0] = static_cast<uint16_t>(std::abs(rpm_left));
//         speed_cmds[1] = static_cast<uint16_t>(std::abs(rpm_right));

//         // Viết logic cấu hình hướng quay 2004, 2005 tương ứng với dấu của rpm_left, rpm_right ở đây...

//         // Đẩy tốc độ xuống driver
//         modbus_write_registers(ctx_, 2006, 2, speed_cmds);

//         return hardware_interface::return_type::OK;
//         }
//         }  // namespace hinson_hardware

//         #include "pluginlib/class_list_macros.hpp"
//         PLUGINLIB_EXPORT_CLASS(
//         hinson_hardware::HinsonSystemHardware, hardware_interface::SystemInterface)


// }


#include "hinson_hardware/hinson_system.hpp"

#include <chrono>
#include <cmath>
#include <cstddef>
#include <limits>
#include <memory>
#include <vector>

#include "hardware_interface/types/hardware_interface_type_values.hpp"
#include "rclcpp/rclcpp.hpp"
#include <modbus/modbus.h>
// gemini 
// #include <logging.hpp>

namespace hinson_hardware
{

hardware_interface::CallbackReturn HinsonSystemHardware::on_init(
  const hardware_interface::HardwareInfo & info)
{
  if (hardware_interface::SystemInterface::on_init(info) !=
      hardware_interface::CallbackReturn::SUCCESS) {
    return hardware_interface::CallbackReturn::ERROR;
  }

  // Khởi tạo vector kích thước 2 (cho 2 bánh)
  hw_positions_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());
  hw_velocities_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());
  hw_commands_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());
  // Trong hinson_system.cpp -> hàm on_init
  // hw_positions_.assign(info_.joints.size(), 0.0);
  // hw_velocities_.assign(info_.joints.size(), 0.0);
  // hw_commands_.assign(info_.joints.size(), 0.0);
  
  prev_hall_counts_.resize(info_.joints.size(), 0);

  // Đọc params từ URDF
  port_ = info_.hardware_parameters["port"];
  baudrate_ = std::stoi(info_.hardware_parameters["baudrate"]);

  for (const hardware_interface::ComponentInfo & joint : info_.joints) {
    if (joint.command_interfaces[0].name != hardware_interface::HW_IF_VELOCITY) {
      RCLCPP_FATAL(rclcpp::get_logger("HinsonSystemHardware"), "Joint '%s' có command interface không hợp lệ. Khuyên dùng 'velocity'.", joint.name.c_str());
      return hardware_interface::CallbackReturn::ERROR;
    }
  }

  return hardware_interface::CallbackReturn::SUCCESS;
}

std::vector<hardware_interface::StateInterface> HinsonSystemHardware::export_state_interfaces()
{
  std::vector<hardware_interface::StateInterface> state_interfaces;
  for (auto i = 0u; i < info_.joints.size(); i++) {
    state_interfaces.emplace_back(hardware_interface::StateInterface(
      info_.joints[i].name, hardware_interface::HW_IF_POSITION, &hw_positions_[i]));
    state_interfaces.emplace_back(hardware_interface::StateInterface(
      info_.joints[i].name, hardware_interface::HW_IF_VELOCITY, &hw_velocities_[i]));
  }
  return state_interfaces;
}

std::vector<hardware_interface::CommandInterface> HinsonSystemHardware::export_command_interfaces()
{
  std::vector<hardware_interface::CommandInterface> command_interfaces;
  for (auto i = 0u; i < info_.joints.size(); i++) {
    command_interfaces.emplace_back(hardware_interface::CommandInterface(
      info_.joints[i].name, hardware_interface::HW_IF_VELOCITY, &hw_commands_[i]));
  }
  return command_interfaces;
}

hardware_interface::CallbackReturn HinsonSystemHardware::on_activate(
  const rclcpp_lifecycle::State & /*previous_state*/)
{
  RCLCPP_INFO(rclcpp::get_logger("HinsonSystemHardware"), "Connecting Modbus at %s, baud %d...", port_.c_str(), baudrate_);

  ctx_ = modbus_new_rtu(port_.c_str(), baudrate_, 'N', 8, 1);
  if (ctx_ == nullptr) {
    RCLCPP_ERROR(rclcpp::get_logger("HinsonSystemHardware"), "Không tạo được libmodbus context!");
    return hardware_interface::CallbackReturn::ERROR;
  }

  modbus_set_slave(ctx_, 10);
  
  if (modbus_connect(ctx_) == -1) {
    RCLCPP_ERROR(rclcpp::get_logger("HinsonSystemHardware"), "Modbus connection failed: %s", modbus_strerror(errno));
    modbus_free(ctx_);
    ctx_ = nullptr;
    return hardware_interface::CallbackReturn::ERROR;
  }

  // --- Reset Fault và Config Driver ---
  uint16_t clear_fault_1[1] = {1};
  uint16_t clear_fault_0[1] = {0};
  uint16_t individual_mode[1] = {1};
  uint16_t enable_motor[2] = {1, 1}; 

  modbus_write_registers(ctx_, 2000, 1, clear_fault_1);
  rclcpp::sleep_for(std::chrono::milliseconds(100));
  modbus_write_registers(ctx_, 2000, 1, clear_fault_0);
  rclcpp::sleep_for(std::chrono::milliseconds(100));
  
  modbus_write_registers(ctx_, 2001, 1, individual_mode);
  modbus_write_registers(ctx_, 2002, 2, enable_motor);

  // Khởi tạo biến về 0
  for (auto i = 0u; i < hw_positions_.size(); i++) {
    hw_positions_[i] = 0.0;
    hw_velocities_[i] = 0.0;
    hw_commands_[i] = 0.0;
  }

  // Đọc xung Hall lần đầu để làm gốc
  uint16_t hall_regs[2];
  // if (modbus_read_registers(ctx_, 1014, 2, hall_regs) == 2) {
  //   prev_hall_counts_[0] = hall_regs[0];
  //   prev_hall_counts_[1] = hall_regs[1];
  // }

  if (modbus_read_input_registers(ctx_, 1014, 2, hall_regs) == 2) {
    prev_hall_counts_[0] = hall_regs[0];
    prev_hall_counts_[1] = hall_regs[1];
  }

  RCLCPP_INFO(rclcpp::get_logger("HinsonSystemHardware"), "System Successfully Activated!");
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn HinsonSystemHardware::on_deactivate(
  const rclcpp_lifecycle::State & /*previous_state*/)
{
  if (ctx_ != nullptr) {
    // Dừng động cơ trước khi ngắt kết nối
    uint16_t stop_cmds[2] = {0, 0};
    modbus_write_registers(ctx_, 2006, 2, stop_cmds);
    
    modbus_close(ctx_);
    modbus_free(ctx_);
    ctx_ = nullptr;
  }
  RCLCPP_INFO(rclcpp::get_logger("HinsonSystemHardware"), "System Deactivated");
  return hardware_interface::CallbackReturn::SUCCESS;
}

// hardware_interface::return_type HinsonSystemHardware::read(
//   const rclcpp::Time & /*time*/, const rclcpp::Duration & period)
// {
//   if (ctx_ == nullptr) return hardware_interface::return_type::ERROR;

//   uint16_t hall_regs[2];
//   // Đọc thanh ghi 1014 (Hall A) và 1015 (Hall B)
//   if (modbus_read_registers(ctx_, 1014, 2, hall_regs) == 2) {
//     for (int i = 0; i < 2; i++) {
//       // Tính chênh lệch xung (Xử lý overflow tự động nhờ tính chất của uint16_t)
//       int16_t delta_pulses = static_cast<int16_t>(hall_regs[i] - prev_hall_counts_[i]);
      
//       // Quy đổi radian (1 vòng = 720 xung -> 1 xung = 2Pi/720 rad)
//       double delta_rad = delta_pulses * (2.0 * M_PI / 720.0);
      
//       hw_positions_[i] += delta_rad;
//       hw_velocities_[i] = delta_rad / period.seconds(); // rad/s
      
//       prev_hall_counts_[i] = hall_regs[i];
//     }
//   }

//   return hardware_interface::return_type::OK;
// }


// gemini  #include <logging.hpp>
// hardware_interface::return_type HinsonSystemHardware::read(
//   const rclcpp::Time & /*time*/, const rclcpp::Duration & period)
// {
//   if (ctx_ == nullptr) return hardware_interface::return_type::ERROR;

//   uint16_t hall_regs[2];
//   // int rc = modbus_read_registers(ctx_, 1014, 2, hall_regs);
//   int rc = modbus_read_input_registers(ctx_, 1014, 2, hall_regs);
  
//   if (rc == 2) {
//     for (int i = 0; i < 2; i++) {
//       int16_t delta_pulses = static_cast<int16_t>(hall_regs[i] - prev_hall_counts_[i]);
//       double delta_rad = delta_pulses * (2.0 * M_PI / 720.0);
      
//       // THÊM ĐOẠN NÀY: Đảo dấu xung encoder của bánh phải (i == 1)
//       if (i == 1) {
//           delta_pulses = -delta_pulses;
//       }

//       hw_positions_[i] += delta_rad;
//       hw_velocities_[i] = delta_rad / period.seconds(); 
      
//       prev_hall_counts_[i] = hall_regs[i];
//     }
//   } else {
//     // FIX: Dùng biến đếm tĩnh để giới hạn số lần in log (khoảng 30 khung hình/giây = 1 giây in 1 lần)
//     static int error_counter = 0;
//     if (error_counter % 30 == 0) { 
//       RCLCPP_WARN(
//         rclcpp::get_logger("HinsonSystemHardware"), 
//         "Lỗi đọc Modbus: %s (Mã lỗi: %d)", modbus_strerror(errno), errno);
//     }
//     error_counter++;
//   }

//   return hardware_interface::return_type::OK;
// }

hardware_interface::return_type HinsonSystemHardware::read(
  const rclcpp::Time & /*time*/, const rclcpp::Duration & period)
{
  if (ctx_ == nullptr) return hardware_interface::return_type::ERROR;

  uint16_t hall_regs[2];
  int rc = modbus_read_input_registers(ctx_, 1014, 2, hall_regs);
  
  if (rc == 2) {
    // DO LẮP DÂY NGƯỢC:
    // hall_regs[0] (Thanh ghi 1014) thực tế đang đọc BÁNH PHẢI
    // hall_regs[1] (Thanh ghi 1015) thực tế đang đọc BÁNH TRÁI
    
    int16_t delta_m0 = static_cast<int16_t>(hall_regs[0] - prev_hall_counts_[0]);
    int16_t delta_m1 = static_cast<int16_t>(hall_regs[1] - prev_hall_counts_[1]);
    
    // Đảo dấu chiều quay của bánh trái (m1) do tính chất đối xứng
    // delta_m0 = -delta_m0;
    delta_m1 = -delta_m1;

    // Tính Radian
    double rad_m0 = delta_m0 * (2.0 * M_PI / 720.0); // Radian bánh Phải
    double rad_m1 = delta_m1 * (2.0 * M_PI / 720.0); // Radian bánh Trái
    
    // Cập nhật lên ROS (ROS quy ước cứng: index 0 là Trái, index 1 là Phải)
    hw_positions_[0] += rad_m1; 
    hw_velocities_[0] = rad_m1 / period.seconds(); 
    
    hw_positions_[1] += rad_m0; 
    hw_velocities_[1] = rad_m0 / period.seconds(); 
    
    prev_hall_counts_[0] = hall_regs[0];
    prev_hall_counts_[1] = hall_regs[1];
  } else {
    static int error_counter = 0;
    if (error_counter % 30 == 0) { 
      RCLCPP_WARN(
        rclcpp::get_logger("HinsonSystemHardware"), 
        "Lỗi đọc Modbus: %s (Mã lỗi: %d)", modbus_strerror(errno), errno);
    }
    error_counter++;
  }

  return hardware_interface::return_type::OK;
}

// hardware_interface::return_type HinsonSystemHardware::write(
//   const rclcpp::Time & /*time*/, const rclcpp::Duration & /*period*/)
// {
//   if (ctx_ == nullptr) return hardware_interface::return_type::ERROR;

//   // cmd_[0] là rad/s bánh trái, cmd_[1] là rad/s bánh phải
//   // Đổi rad/s -> RPM động cơ: RPM = (omega * 60 / 2Pi) * 30 tỷ số truyền = omega * 900 / Pi
//   int rpm_left = hw_commands_[0] * 900.0 / M_PI;
//   int rpm_right = hw_commands_[1] * 900.0 / M_PI;

//   uint16_t dir_cmds[2];
//   // Quy ước: 0 là tới, 1 là lùi (tùy thuộc vào thực tế nối dây của nhóm)
//   dir_cmds[0] = (rpm_left >= 0) ? 0 : 1; 
//   dir_cmds[1] = (rpm_right >= 0) ? 1 : 0;

//   uint16_t speed_cmds[2];
//   speed_cmds[0] = static_cast<uint16_t>(std::abs(rpm_left));
//   speed_cmds[1] = static_cast<uint16_t>(std::abs(rpm_right));

//   // Ghi đồng thời hướng (2004-2005) và tốc độ (2006-2007)
//   modbus_write_registers(ctx_, 2004, 2, dir_cmds);
//   modbus_write_registers(ctx_, 2006, 2, speed_cmds);

//   return hardware_interface::return_type::OK;
// }

// hardware_interface::return_type HinsonSystemHardware::write(
//   const rclcpp::Time & /*time*/, const rclcpp::Duration & /*period*/)
// {
//   if (ctx_ == nullptr) return hardware_interface::return_type::ERROR;

//   // Lấy lệnh từ ROS: hw_commands_[0] là bánh Trái, hw_commands_[1] là bánh Phải
//   int rpm_left_ros = hw_commands_[0] * 900.0 / M_PI;
//   int rpm_right_ros = hw_commands_[1] * 900.0 / M_PI;

//   uint16_t dir_cmds[2];
//   uint16_t speed_cmds[2];

//   // Ghi xuống Kênh 0 của Driver (Điều khiển BÁNH PHẢI thực tế)
//   dir_cmds[0] = (rpm_right_ros >= 0) ? 1 : 0; 
//   speed_cmds[0] = static_cast<uint16_t>(std::abs(rpm_right_ros));

//   // Ghi xuống Kênh 1 của Driver (Điều khiển BÁNH TRÁI thực tế)
//   dir_cmds[1] = (rpm_left_ros >= 0) ? 1 : 0;
//   speed_cmds[1] = static_cast<uint16_t>(std::abs(rpm_left_ros));

//   // Đẩy cả 2 mảng xuống Modbus cùng lúc
//   modbus_write_registers(ctx_, 2004, 2, dir_cmds);
//   modbus_write_registers(ctx_, 2006, 2, speed_cmds);

//   return hardware_interface::return_type::OK;
// }

hardware_interface::return_type HinsonSystemHardware::write(
  const rclcpp::Time & /*time*/, const rclcpp::Duration & /*period*/)
{
  if (ctx_ == nullptr) return hardware_interface::return_type::ERROR;

  // 1. Lấy lệnh từ ROS: [0] là Trái, [1] là Phải
  int rpm_left = hw_commands_[0] * 900.0 / M_PI;
  int rpm_right = hw_commands_[1] * 900.0 / M_PI;

  uint16_t dir_cmds[2];
  uint16_t speed_cmds[2];

  // 2. Ghi xuống Kênh 0 của Driver (Nối với BÁNH PHẢI vật lý)
  // Logic: Tiến là 0, Lùi là 1
  dir_cmds[0] = (rpm_right >= 0) ? 0 : 1; 
  speed_cmds[0] = static_cast<uint16_t>(std::abs(rpm_right));

  // 3. Ghi xuống Kênh 1 của Driver (Nối với BÁNH TRÁI vật lý)
  // Logic: Tiến là 1, Lùi là 0 (vì lắp đối xứng)
  dir_cmds[1] = (rpm_left >= 0) ? 1 : 0;
  speed_cmds[1] = static_cast<uint16_t>(std::abs(rpm_left));

  // 4. Đẩy 2 mảng xuống Modbus
  modbus_write_registers(ctx_, 2004, 2, dir_cmds);
  modbus_write_registers(ctx_, 2006, 2, speed_cmds);

  return hardware_interface::return_type::OK;
}

}  // namespace hinson_hardware

#include "pluginlib/class_list_macros.hpp"
PLUGINLIB_EXPORT_CLASS(
  hinson_hardware::HinsonSystemHardware, hardware_interface::SystemInterface)