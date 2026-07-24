# Danh gia giao dien dieu khien khong day cho AMR

Ngay danh gia: 2026-07-09

## Ket luan nhanh

Project da co nen tang web dashboard de laptop khac ket noi qua Wi-Fi noi bo va giao viec/dieu khien robot. Tuy nhien muc do hien tai nen xem la "prototype van hanh duoc" hon la mot he thong giao viec khong day hoan chinh, vi con thieu tai lieu setup mang, bao mat/truy cap, watchdog an toan khi mat ket noi, va quy trinh dong goi chay on dinh tren laptop dat tren robot.

## Doi chieu voi cac y da neu

### 1. Can xay dung giao dien nguoi dung ket noi khong day de giao viec cho robot

Trang thai: Da co mot phan lon.

Bang chung trong project:
- `web/amr_dashboard/index.html`: co dashboard web voi Connect, Teleop control, Robot Status, Station control, SLAM, Localization, Process, Setpoint list.
- `web/amr_dashboard/js/ros.js`: ket noi rosbridge qua WebSocket. Ho tro LAN `ws://IP:9090` va remote tunnel `wss://host/rosbridge`.
- `web/amr_dashboard/js/navigation.js`: gui goal Nav2 qua service `/send_nav_goal`, huy qua `/cancel_nav`, nhan trang thai `/web_nav_status`.
- `web/amr_dashboard/js/stations.js`: tao setpoint, go to station, docking/load/unload workflow, publish mission.
- `web/amr_dashboard/js/process.js`: tao, luu, mo va chay process gom nhieu setpoint.
- `web/amr_dashboard/js/map.js`: hien thi map, robot pose, plan path, dat initial pose, chon goal tren canvas.
- `web/amr_dashboard/js/stm32.js`: hien thi STM32/conveyor status va goi service chay bang tai.

Danh gia:
- UI giao viec da co: chon station, auto route/process, save/load process, navigation goal.
- UI dieu khien tay da co: publish `/cmd_vel_web`.
- UI quan sat vi tri hien tai va ban do da co: subscribe map/pose/odom.
- Chua thay co co che dang nhap, phan quyen that su, audit log, hoac xac nhan lenh nguy hiem.

### 2. Tam thoi su dung laptop ca nhan de dat tren robot va dieu khien

Trang thai: Da phu hop voi cau truc hien tai.

Bang chung trong project:
- `src/amr_lan_3/launch/launch_robot.launch.py`: launch robot thuc gom controller, EKF, IMU, laser filter, web support, mission supervisor.
- `src/amr_lan_3/launch/web_support.launch.py`: chay `twist_mux`, `map_bridge_node`, `nav_pose_bridge_node`, `mission_client_node`, `stm32_conveyor_bridge_node`, va rosbridge port `9090`.
- `scripts/amr_tabs.sh` va `scripts/amr_terminator.sh`: co tab WEB, NGROK, ROBOT, SLAM, LOC, NAV de khoi dong nhanh.
- `scripts/amr_web_server.py`: serve dashboard static tren port `8080` va proxy `/rosbridge` ve `ws://127.0.0.1:9090`.

Danh gia:
- Kien truc hien tai dung mot laptop tren robot lam may chay ROS 2 va web server la hop ly.
- Laptop tren robot can chay `launch_robot.launch.py` va `scripts/amr_web_server.py`; khi can remote qua internet moi can `ngrok`.
- Chua thay file huong dan rieng cho che do "laptop tren robot + laptop dieu khien qua Wi-Fi noi bo".

### 3. Mot laptop khac ket noi Wi-Fi noi bo de lam giao dien dieu khien robot va xem vi tri hien tai tren ban do

Trang thai: Da co nen tang, can bo sung huong dan va do on dinh.

Bang chung trong project:
- `scripts/amr_web_server.py` bind mac dinh `0.0.0.0:8080`, laptop khac trong cung mang co the mo `http://ROBOT_IP:8080`.
- `src/amr_lan_3/launch/web_support.launch.py` chay rosbridge voi `address=0.0.0.0`, port `9090`.
- `web/amr_dashboard/js/ros.js` tu build URL LAN theo dang `ws://ROBOT_IP:9090`.
- `web/amr_dashboard/js/status.js` doc `/odometry/filtered`.
- `src/amr_web_bridge/amr_web_bridge/nav_pose_bridge_node.py` publish `/robot_pose_map` tu TF `map -> base_footprint`.
- `web/amr_dashboard/js/map.js` ve map va robot pose tren canvas.

Danh gia:
- Ve mat ky thuat, laptop dieu khien trong cung Wi-Fi co the mo dashboard va ket noi den rosbridge tren robot.
- Neu dung `scripts/amr_web_server.py`, nen uu tien vao `http://ROBOT_IP:8080`, sau do bam Connect voi IP robot.
- Chua thay co script hien IP robot, kiem tra port, hoac huong dan firewall/network discovery.

## Nhung phan con thieu nen bo sung

### Uu tien cao

1. Tai lieu van hanh Wi-Fi noi bo
   - Them huong dan: laptop tren robot chay lenh nao, laptop dieu khien mo URL nao, cach lay IP robot, cach test `ping`, `curl http://ROBOT_IP:8080`, va test rosbridge port `9090`.
   - Ghi ro che do LAN khong can ngrok.

2. Watchdog an toan cho teleop/mat ket noi
   - Hien UI dang publish `/cmd_vel_web` khi giu nut, nhung can dam bao khi browser mat ket noi/treo thi robot dung sau timeout.
   - Nen co node watchdog rieng hoac cau hinh timeout trong mux/controller de stop neu `/cmd_vel_web` mat heartbeat.

3. Bao mat truy cap dashboard
   - Hien rosbridge va web server mo tren `0.0.0.0`, ai trong cung mang co the ket noi neu biet IP.
   - Nen them toi thieu password/token noi bo, hoac gioi han IP/VLAN khi demo/van hanh.

4. Dong goi khoi dong mot lenh
   - Hien co nhieu script/tab, nhung nen co mot script/systemd service cho laptop tren robot: ROS robot stack + web server + log.
   - Nen co file `.env`/config de set map mac dinh, mode sim/real, port web, port rosbridge.

5. Nut dung khan cap va trang thai an toan ro hon tren UI
   - UI co Cancel navigation va Stop teleop, nhung can tach "Stop motion / E-stop software" ro rang.
   - Nen hien trang thai emergency, Nav2 active/inactive, STM32 alive, lidar/odom/map OK.

### Uu tien trung binh

6. Trang thai ket noi chi tiet
   - Hien tai co connected/disconnected, nen them cac check rieng: Web server, rosbridge, Nav2 action, map bridge, STM32, localization.

7. Quan ly role that su
   - UI co tab Operator/Setter, nhung chua phai phan quyen.
   - Nen khoa cac chuc nang setup nhu SLAM, set initial pose, save map, edit setpoint bang password hoac che do admin.

8. Chuan hoa du lieu setpoint/process
   - Da luu theo `~/MAP_DATA/{map}/setpoint` va `process`, day la tot.
   - Nen them export/import, backup, va validate setpoint trung ten/sai toa do.

9. Tai lieu troubleshooting
   - Nen co bang loi thuong gap: khong thay map, robot khong di, Nav2 not ready, STM32 disconnected, rosbridge khong connect, sai IP, firewall chan port.

10. Kiem thu tren man hinh laptop/tablet
   - Dashboard da co responsive CSS, nhung nen test tren man hinh nho va cam ung vi day la giao dien dieu khien robot thuc.

### Uu tien thap nhung nen co khi demo/san pham

11. Log lich su giao viec
   - Luu ai bam lenh nao, luc nao, station nao, ket qua thanh cong/that bai.

12. Hien thi pin va sensor health that
   - UI co field `Pin: N/A`; nen noi vao topic battery/voltage neu phan cung co.

13. Ten mien noi bo de khoi nho IP
   - Co the dung hostname, mDNS, hoac router DHCP reservation: `http://amr-robot.local:8080`.

14. Che do kiosk/operator
   - Laptop dieu khien co the mo full screen, an cac chuc nang setup, chi giu station/process/status.

## Recommendation kien truc gan han

Kien truc nen dung tiep:

Laptop tren robot:
- Chay ROS 2 robot stack: `launch_robot.launch.py`.
- Chay web support/rosbridge thong qua launch robot.
- Chay dashboard server: `python3 scripts/amr_web_server.py --host 0.0.0.0 --port 8080`.
- Ket noi vao Wi-Fi noi bo co IP co dinh hoac DHCP reservation.

Laptop dieu khien:
- Cung Wi-Fi noi bo.
- Mo `http://ROBOT_IP:8080`.
- Bam Connect voi `ROBOT_IP`.
- Theo doi map/pose, chon station/process, gui goal, dung khi can.

Viec nen lam tiep ngay:
1. Viet README rieng cho LAN operation.
2. Them watchdog dung robot khi mat `/cmd_vel_web`.
3. Them password/token cho dashboard hoac gioi han truy cap trong mang noi bo.
4. Tao script start/stop mot lenh cho laptop tren robot.
5. Them checklist truoc khi van hanh: map loaded, localization OK, Nav2 ready, STM32 connected, lidar/odom OK, emergency clear.

