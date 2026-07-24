# -*- coding: utf-8 -*-
"""GUI test giao thức UART giữa ROS2 và STM32 conveyor board."""

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


DEFAULT_BAUD = "256000"
RX_BUFFER_LIMIT = 4096

# Bảng mã lấy từ chương trình conveyor nguyên khối cũ.
AUDIO_TRACK_CODES = {
    1: 0x01,
    2: 0x02,
    3: 0x04,
    4: 0x08,
    16: 0x0F,
    17: 0x0E,
    18: 0x0D,
    19: 0x0C,
    20: 0x0B,
    21: 0x0A,
    22: 0x09,
    24: 0x07,
    25: 0x06,
    26: 0x05,
    28: 0x03,
}


class STM32UARTTool(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("STM32 Conveyor UART Tool - ROS2 Commands")
        self.geometry("1120x760")
        self.minsize(980, 650)

        self.ser = None
        self.rx_thread = None
        self.rx_running = False
        self.rx_queue = queue.Queue()
        self.write_lock = threading.Lock()
        self.closing = False
        self.ping_sequence = 0
        self.command_history = []
        self.command_buttons = []

        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value=DEFAULT_BAUD)
        self.append_crlf_var = tk.BooleanVar(value=True)
        self.show_tx_var = tk.BooleanVar(value=True)
        self.auto_scroll_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="DISCONNECTED")

        self.system_state_var = tk.StringVar(value="--")
        self.active_belt_var = tk.StringVar(value="--")
        self.direction_var = tk.StringVar(value="--")
        self.estop_var = tk.StringVar(value="--")
        self.sensor_var = tk.StringVar(value="S1:-  S2:-  S3:-  S4:-")
        self.cargo_var = tk.StringVar(value="Cargo B1:-  B2:-")

        audio_values = [f"Bài {track}  (mã 0x{code:02X})" for track, code in AUDIO_TRACK_CODES.items()]
        self.audio_var = tk.StringVar(value=audio_values[0])
        self.audio_values = audio_values

        self._build_ui()
        self.refresh_ports(show_message=False)
        self.after(50, self.process_rx_queue)

    # ================= UI =================

    def _build_ui(self):
        self._build_connection_panel()
        self._build_status_panel()
        self._build_command_panel()
        self._build_manual_panel()
        self._build_log_panel()

    def _build_connection_panel(self):
        frame = ttk.LabelFrame(self, text="Kết nối UART")
        frame.pack(fill="x", padx=10, pady=(8, 4))

        ttk.Label(frame, text="COM:").grid(row=0, column=0, padx=(8, 4), pady=7)
        self.port_combo = ttk.Combobox(frame, textvariable=self.port_var, width=17, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=4, pady=7)

        ttk.Button(frame, text="Quét lại", command=self.refresh_ports).grid(row=0, column=2, padx=4, pady=7)

        ttk.Label(frame, text="Baud:").grid(row=0, column=3, padx=(14, 4), pady=7)
        self.baud_combo = ttk.Combobox(
            frame,
            textvariable=self.baud_var,
            width=11,
            values=["9600", "57600", "115200", "230400", "256000", "460800", "921600"],
        )
        self.baud_combo.grid(row=0, column=4, padx=4, pady=7)

        self.btn_open = ttk.Button(frame, text="Kết nối", command=self.open_serial)
        self.btn_open.grid(row=0, column=5, padx=(12, 4), pady=7)
        self.btn_close = ttk.Button(frame, text="Ngắt", command=self.close_serial, state="disabled")
        self.btn_close.grid(row=0, column=6, padx=4, pady=7)

        self.status_label = tk.Label(frame, textvariable=self.status_var, fg="#b00020", anchor="w")
        self.status_label.grid(row=0, column=7, padx=12, pady=7, sticky="ew")
        frame.columnconfigure(7, weight=1)

        ttk.Checkbutton(frame, text="CRLF", variable=self.append_crlf_var).grid(row=0, column=8, padx=5)
        ttk.Checkbutton(frame, text="Hiện TX", variable=self.show_tx_var).grid(row=0, column=9, padx=5)
        ttk.Checkbutton(frame, text="Auto scroll", variable=self.auto_scroll_var).grid(row=0, column=10, padx=(5, 8))

    def _build_status_panel(self):
        frame = ttk.LabelFrame(self, text="Trạng thái từ telemetry")
        frame.pack(fill="x", padx=10, pady=4)

        fields = [
            ("System", self.system_state_var),
            ("Active belt", self.active_belt_var),
            ("Direction", self.direction_var),
            ("ESTOP source", self.estop_var),
        ]
        for column, (name, variable) in enumerate(fields):
            ttk.Label(frame, text=f"{name}:").grid(row=0, column=column * 2, padx=(8, 3), pady=5, sticky="w")
            ttk.Label(frame, textvariable=variable, width=11).grid(
                row=0, column=column * 2 + 1, padx=(0, 10), pady=5, sticky="w"
            )

        ttk.Label(frame, textvariable=self.cargo_var).grid(row=1, column=0, columnspan=3, padx=8, pady=5, sticky="w")
        ttk.Label(frame, textvariable=self.sensor_var).grid(row=1, column=3, columnspan=5, padx=8, pady=5, sticky="w")

    def _build_command_panel(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="x", padx=10, pady=4)

        ros_tab = ttk.Frame(notebook)
        audio_tab = ttk.Frame(notebook)
        notebook.add(ros_tab, text="Lệnh ROS2")
        notebook.add(audio_tab, text="Loa")

        system = ttk.LabelFrame(ros_tab, text="System")
        system.pack(side="left", fill="both", expand=True, padx=(6, 3), pady=6)
        self._command_button(system, "HELLO", lambda: self.send_command("$HELLO,test,PC,1.0"), 0, 0)
        self._command_button(system, "PING", self.send_ping, 0, 1)
        self._command_button(system, "RESET ESTOP", lambda: self.send_command("$CMD,RESET_ESTOP"), 1, 0, 2)

        belt1 = ttk.LabelFrame(ros_tab, text="Băng tải 1 · S1 ↔ S3")
        belt1.pack(side="left", fill="both", expand=True, padx=3, pady=6)
        self._command_button(belt1, "START LOAD 1", lambda: self.send_command("$CMD,START,1"), 0, 0, 2)
        self._command_button(belt1, "UNLOAD LEFT", lambda: self.send_command("$CMD,STOP,1,LEFT"), 1, 0)
        self._command_button(belt1, "UNLOAD RIGHT", lambda: self.send_command("$CMD,STOP,1,RIGHT"), 1, 1)

        belt2 = ttk.LabelFrame(ros_tab, text="Băng tải 2 · S2 ↔ S4")
        belt2.pack(side="left", fill="both", expand=True, padx=(3, 6), pady=6)
        self._command_button(belt2, "START LOAD 2", lambda: self.send_command("$CMD,START,2"), 0, 0, 2)
        self._command_button(belt2, "UNLOAD LEFT", lambda: self.send_command("$CMD,STOP,2,LEFT"), 1, 0)
        self._command_button(belt2, "UNLOAD RIGHT", lambda: self.send_command("$CMD,STOP,2,RIGHT"), 1, 1)

        selector = ttk.LabelFrame(audio_tab, text="Chọn bài phát trực tiếp")
        selector.pack(side="left", fill="both", expand=True, padx=(6, 3), pady=6)
        self.audio_combo = ttk.Combobox(
            selector,
            textvariable=self.audio_var,
            values=self.audio_values,
            state="readonly",
            width=26,
        )
        self.audio_combo.grid(row=0, column=0, padx=8, pady=10, sticky="ew")
        self._command_button(selector, "PHÁT BÀI ĐÃ CHỌN", self.send_selected_audio, 0, 1)
        ttk.Label(selector, text="Frame: $CMD,Buzzer,<bài>").grid(
            row=1, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="w"
        )
        selector.columnconfigure(0, weight=1)

        ros_audio = ttk.LabelFrame(audio_tab, text="Các bài đang dùng")
        ros_audio.pack(side="left", fill="both", expand=True, padx=(3, 6), pady=6)
        quick_tracks = [1, 2, 3, 4, 16, 17, 18, 19, 20, 21]
        for index, track in enumerate(quick_tracks):
            self._command_button(
                ros_audio,
                f"Bài {track}",
                lambda selected=track: self.send_command(f"$CMD,Buzzer,{selected}"),
                index // 5,
                index % 5,
            )

    def _command_button(self, parent, text, command, row, column, columnspan=1):
        button = ttk.Button(parent, text=text, command=command, state="disabled")
        button.grid(row=row, column=column, columnspan=columnspan, padx=6, pady=6, sticky="ew")
        self.command_buttons.append(button)
        for index in range(column, column + columnspan):
            parent.columnconfigure(index, weight=1)
        return button

    def _build_manual_panel(self):
        frame = ttk.LabelFrame(self, text="Gửi thủ công")
        frame.pack(fill="x", padx=10, pady=4)

        self.send_entry = ttk.Combobox(frame, values=self.command_history)
        self.send_entry.pack(side="left", fill="x", expand=True, padx=8, pady=7)
        self.send_entry.bind("<Return>", lambda _event: self.send_manual())
        self.btn_send = ttk.Button(frame, text="Gửi", command=self.send_manual, state="disabled")
        self.btn_send.pack(side="left", padx=(0, 8), pady=7)

    def _build_log_panel(self):
        frame = ttk.LabelFrame(self, text="Log UART")
        frame.pack(fill="both", expand=True, padx=10, pady=(4, 8))

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", padx=6, pady=(5, 0))
        ttk.Button(toolbar, text="Xóa log", command=self.clear_log).pack(side="left")
        ttk.Button(toolbar, text="Hướng dẫn", command=self.show_help).pack(side="left", padx=6)

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text = tk.Text(text_frame, wrap="word", height=16, state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

        self.log_text.tag_configure("RX", foreground="#1455a0")
        self.log_text.tag_configure("TX", foreground="#16702b")
        self.log_text.tag_configure("ACK", foreground="#00695c")
        self.log_text.tag_configure("NACK", foreground="#c62828")
        self.log_text.tag_configure("EVENT", foreground="#b06000")
        self.log_text.tag_configure("ERR", foreground="#c62828")
        self.log_text.tag_configure("SYS", foreground="#6a1b9a")

    # ================= Serial =================

    def refresh_ports(self, show_message=True):
        if serial is None:
            if show_message:
                messagebox.showerror("Thiếu thư viện", "Chạy: python -m pip install pyserial")
            return

        previous = self.port_var.get()
        ports = [port.device for port in list_ports.comports()]
        self.port_combo["values"] = ports

        if previous in ports:
            self.port_var.set(previous)
        elif ports:
            self.port_var.set(ports[0])
        else:
            self.port_var.set("")

        if show_message:
            self.log_sys("Đã quét COM: " + (", ".join(ports) if ports else "không tìm thấy cổng"))

    def open_serial(self):
        if serial is None:
            messagebox.showerror("Thiếu thư viện", "Chạy: python -m pip install pyserial")
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("Chưa chọn COM", "Hãy chọn cổng COM trước.")
            return

        try:
            baud = int(self.baud_var.get().strip())
        except ValueError:
            messagebox.showerror("Sai baud", "Baudrate phải là số, ví dụ 256000.")
            return

        self.close_serial(log_message=False)

        try:
            connection = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.05,
                write_timeout=0.5,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            try:
                connection.setDTR(False)
                connection.setRTS(False)
            except Exception:
                pass

            connection.reset_input_buffer()
            self.ser = connection
            self.rx_running = True
            self.rx_thread = threading.Thread(target=self.rx_worker, args=(connection,), daemon=True)
            self.rx_thread.start()

            self._set_connected_ui(True)
            self.status_var.set(f"CONNECTED {port} @ {baud}")
            self.status_label.configure(fg="#087f23")
            self.log_sys(f"Đã mở {port}, baud {baud}, 8N1, no flow control")
        except Exception as error:
            self.ser = None
            self._set_connected_ui(False)
            self.log_err(f"Không mở được COM: {error}")
            messagebox.showerror("Lỗi mở COM", str(error))

    def close_serial(self, log_message=True):
        connection = self.ser
        was_open = connection is not None
        self.rx_running = False
        self.ser = None

        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

        self._set_connected_ui(False)
        self.status_var.set("DISCONNECTED")
        if hasattr(self, "status_label"):
            self.status_label.configure(fg="#b00020")
        if log_message and was_open:
            self.log_sys("Đã đóng COM")

    def _set_connected_ui(self, connected):
        if not hasattr(self, "btn_open"):
            return
        self.btn_open.configure(state="disabled" if connected else "normal")
        self.btn_close.configure(state="normal" if connected else "disabled")
        self.btn_send.configure(state="normal" if connected else "disabled")
        for button in self.command_buttons:
            button.configure(state="normal" if connected else "disabled")

    def rx_worker(self, connection):
        buffer = bytearray()

        while self.rx_running and self.ser is connection:
            try:
                data = connection.read(256)
                if not data:
                    continue

                buffer.extend(data)
                while b"\n" in buffer:
                    raw_line, _, buffer = buffer.partition(b"\n")
                    line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
                    if line:
                        self.rx_queue.put(("RX", line))

                if len(buffer) > RX_BUFFER_LIMIT:
                    self.rx_queue.put(("ERR", "RX buffer vượt giới hạn; đã xóa dữ liệu không có newline"))
                    buffer.clear()
            except (OSError, serial.SerialException) as error:
                if self.rx_running and self.ser is connection:
                    self.rx_queue.put(("DISCONNECTED", f"Mất kết nối UART: {error}"))
                break
            except Exception as error:
                if self.rx_running and self.ser is connection:
                    self.rx_queue.put(("ERR", f"RX lỗi: {error}"))
                break

    # ================= Commands =================

    def send_ping(self):
        self.ping_sequence += 1
        self.send_command(f"$PING,{self.ping_sequence}")

    def send_selected_audio(self):
        selection = self.audio_var.get()
        try:
            track = int(selection.split()[1])
        except (IndexError, ValueError):
            self.log_err("Không đọc được số bài đã chọn.")
            return
        self.send_command(f"$CMD,Buzzer,{track}")

    def send_manual(self):
        text = self.send_entry.get().strip()
        if not text:
            return
        self.send_command(text)
        if text not in self.command_history:
            self.command_history.insert(0, text)
            del self.command_history[20:]
            self.send_entry.configure(values=self.command_history)
        self.send_entry.set("")

    def send_command(self, text):
        connection = self.ser
        if connection is None or not connection.is_open:
            self.log_err("Chưa mở COM.")
            return False

        text = str(text).strip("\r\n")
        if not text:
            return False
        payload = text + ("\r\n" if self.append_crlf_var.get() else "")

        try:
            with self.write_lock:
                connection.write(payload.encode("utf-8"))
                connection.flush()
            if self.show_tx_var.get():
                self.log_tx(text)
            return True
        except Exception as error:
            self.log_err(f"TX lỗi: {error}")
            return False

    # ================= Receive and telemetry =================

    def process_rx_queue(self):
        try:
            while True:
                kind, message = self.rx_queue.get_nowait()
                if kind == "RX":
                    self.process_frame(message)
                elif kind == "DISCONNECTED":
                    self.log_err(message)
                    self.close_serial(log_message=False)
                else:
                    self.log_err(message)
        except queue.Empty:
            pass

        if not self.closing:
            self.after(50, self.process_rx_queue)

    def process_frame(self, message):
        fields = message.split(",")
        frame_type = fields[0].upper() if fields else ""

        if frame_type == "$TELEMETRY":
            self._update_telemetry(fields)
            self.append_log("RX", message)
        elif frame_type == "$ACK" or frame_type in ("$HELLO_ACK", "$PONG"):
            self.append_log("ACK", message)
        elif frame_type == "$NACK":
            self.append_log("NACK", message)
        elif frame_type == "$EVENT":
            self.append_log("EVENT", message)
        else:
            self.append_log("RX", message)

    def _update_telemetry(self, fields):
        if len(fields) < 5:
            self.log_err("Telemetry sai định dạng: " + ",".join(fields))
            return

        state = fields[1]
        bits = fields[2]
        self.system_state_var.set(state)
        self.active_belt_var.set(fields[3])
        self.direction_var.set(fields[4])
        self.estop_var.set(fields[5] if len(fields) >= 6 else "0")

        if len(bits) >= 6 and all(bit in "01" for bit in bits[:6]):
            self.cargo_var.set(f"Cargo B1:{bits[0]}  B2:{bits[1]}")
            self.sensor_var.set(
                "  ".join(f"S{index}:{value}" for index, value in enumerate(bits[2:6], start=1))
            )

    # ================= Log =================

    @staticmethod
    def timestamp():
        return time.strftime("%H:%M:%S")

    def append_log(self, tag, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{self.timestamp()}] {tag}: {message}\n", tag)
        self.log_text.configure(state="disabled")
        if self.auto_scroll_var.get():
            self.log_text.see("end")

    def log_rx(self, message):
        self.append_log("RX", message)

    def log_tx(self, message):
        self.append_log("TX", message)

    def log_err(self, message):
        self.append_log("ERR", message)

    def log_sys(self, message):
        self.append_log("SYS", message)

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def show_help(self):
        messagebox.showinfo(
            "Hướng dẫn test",
            "UART: 256000, 8N1, no flow control\n\n"
            "Belt 1: $CMD,START,1 / $CMD,STOP,1,LEFT|RIGHT\n"
            "Belt 2: $CMD,START,2 / $CMD,STOP,2,LEFT|RIGHT\n"
            "Reset ESTOP: $CMD,RESET_ESTOP\n"
            "Chọn bài loa: $CMD,Buzzer,<số_bài>\n"
            "START sau STOP sẽ tự mở khóa STOP_LOCK.\n\n"
            "Dây UART:\n"
            "USB-UART TX → STM32 PA10 RX\n"
            "USB-UART RX ← STM32 PA9 TX\n"
            "GND nối chung",
        )

    def on_close(self):
        self.closing = True
        self.close_serial(log_message=False)
        self.destroy()


if __name__ == "__main__":
    app = STM32UARTTool()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
