# COBBLEVERSE cho Cobblemon 1.8

Bản port không chính thức của modpack [COBBLEVERSE](https://modrinth.com/modpack/cobbleverse) 1.7.42 (Minecraft 1.21.1, Fabric) sang Cobblemon 1.8.4, dùng cho một server riêng. Repo chứa công cụ build file `.mrpack`, cấu hình client và cấu hình server Docker.

## Cấu trúc

```
port.json            mọi thay đổi so với COBBLEVERSE gốc
build.sh             build dist/latest.mrpack từ pack gốc và port.json
overrides/           file chép đè vào pack (bộ phím, ghi đè dependency của TMCraft)
tools/pack/          các bước của build.sh
tools/inspect/       công cụ kiểm tra mod và dữ liệu
tools/client/        chạy thử client, tìm lỗi bằng chia đôi, áp phím vào profile
server/              docker compose cho server chơi và server test
.cache/ build/ dist/ file tải về, file trung gian, pack đầu ra (không commit)
```

## Build

Cần `python3`, `jq`, `unzip` và mạng tới Modrinth.

```sh
./build.sh
```

Kết quả nằm ở `dist/COBBLEVERSE-1.7.42-cm1.8.4.mrpack`, có symlink `dist/latest.mrpack`. Lần đầu chạy mất khoảng 10 phút vì phải tải pack gốc, khoảng 45 jar và hỏi Modrinth API cho từng file. Các lần sau dùng cache trong `.cache/` nên nhanh hơn nhiều.

`build.sh` chạy theo thứ tự:

1. Tải pack gốc theo `port.json` và kiểm tra sha512.
2. Tra Modrinth cho từng file trong pack (`build/analysis.json`).
3. Tải jar cũ và jar mới của các mod liên quan tới Cobblemon (`build/plan.json`).
4. Gộp ba chiều các datapack của COBBLEVERSE lên dữ liệu của jar mới (`build/merge.log` ghi các chỗ xung đột).
5. Sinh `overrides/config/defaultoptions/keybindings.txt` từ bộ phím của pack gốc và bố cục trong `tools/pack/keybinds.py`.
6. Ghi file `.mrpack`.

## Thay đổi so với COBBLEVERSE 1.7.42

Danh sách đầy đủ nằm trong `port.json`.

- Cobblemon 1.7.3 lên 1.8.4, cùng 16 addon lên bản hỗ trợ 1.8 (Mega Showdown, RCT, Raid Dens, TMCraft, PokeNav, Fight or Flight...).
- Bỏ Better Pokedex Scanner, vì mod khai báo `cobblemon <1.8.0` và chưa có bản cho 1.8.
- Bỏ resource pack `ATMxMSD RP.zip` (v3.6.1, làm cho Cobblemon 1.7). Trên 1.8, pack này làm client ngừng vẽ sau màn hình load: game vẫn chạy và nhận click nhưng màn hình đứng ở khung splash. Thay bằng mod ATM x MSD v5.0 của cùng tác giả.
- TMCraft 1.4.19 chỉ nhận đúng Cobblemon 1.8.3. `overrides/config/fabric_loader_dependencies.json` nới thành `>=1.8.3 <1.9`.
- Dòng phiên bản ở góc menu chính ghi thêm "Cobblemon 1.8.4".
- Bộ phím mới, mô tả ở mục dưới.

Các addon chưa có bản cho 1.8 (LumyMon, CobbleFurnies, CobbleCuisine, Legendary Monuments bản COBBLEVERSE, Battle Extras...) giữ nguyên. `tools/inspect/linkcheck.py` đã kiểm tra bytecode của chúng: không mod nào gọi tới class, method hay field đã bị xóa trong Cobblemon 1.8.4.

## Gộp datapack

COBBLEVERSE ghi đè khoảng 1000 file spawn và nhiều file species, loot, advancement của Cobblemon 1.7. Cobblemon 1.8 làm lại gần hết các file đó: weight spawn nhân khoảng 10 lần, điều kiện spawn đổi, thêm spawn theo đàn. `tools/pack/merge.py` xử lý từng file theo các quy tắc sau:

- File COBBLEVERSE chép nguyên từ 1.7 thì bỏ, để dùng bản của 1.8.
- Phía nào giữ nguyên thì lấy phía còn lại. Cả hai cùng sửa một chỗ thì giữ bản COBBLEVERSE và ghi vào `build/merge.log`.
- Danh sách spawn gộp theo `id`. Weight của COBBLEVERSE nhân theo đúng tỉ lệ 1.8 đã áp cho spawn đó. Spawn không có trong 1.7 nhân x10, riêng bucket ultra-rare nhân x8.
- 44 loài mà Cobblemon 1.8 mới hỗ trợ chính thức dùng spawn của 1.8 thay cho spawn tạm của COBBLEVERSE.
- Advancement mà 1.8 dời sang thư mục khác được gộp vào đường dẫn mới. Phần thưởng bản đồ gym khi chế Pokédex vẫn còn.

Mod trong mục `add` của `port.json` không tham gia gộp. ATM x MSD có vài file trùng đường dẫn với Mega Showdown, và gộp ba chiều giữa hai mod khác nhau làm mất dữ liệu (Darkrai mất thuộc tính bay).

## Client

1. Tạo profile trong Modrinth App từ file `dist/latest.mrpack`. Khi app đang mở, chạy `modrinth-app dist/latest.mrpack` sẽ hiện hộp thoại cài.
2. Settings của profile, mục **Syncing**: bật **Unsync game settings**. Nếu không, Modrinth chép `options.txt` của profile khác vào, ghi đè bộ phím và bật fullscreen.
3. Lần đầu mở game mất khoảng 2 phút.

Nếu bộ phím đã bị ghi đè, tắt game rồi chạy:

```sh
python3 -I tools/client/apply_keys.py overrides/config/defaultoptions/keybindings.txt \
  ~/.local/share/ModrinthApp/profiles/<tên profile>/options.txt
```

Script giữ nguyên các thiết lập khác và lưu bản cũ thành `options.txt.bak`.

### Bộ phím

| Nhóm | Phím |
|---|---|
| Pokémon | `R` thả hoặc thu, `Z` / `X` Pokémon trước / sau, `C` Summary, `G` bắt đầu trận (Fight or Flight) |
| Menu Pokémon | `N` PokéNav, `P` PC, `Y` Mega Evolve |
| Cưỡi | `Space` lên, `Shift` xuống, `Ctrl` tăng tốc, `Alt` nhìn tự do, `V` xuống khỏi Pokémon |
| Chuột | `Mouse 4` zoom (giữ), `Mouse 5` ping, chuột giữa sắp xếp túi và rương |
| Đồ và bản đồ | `B` túi, `H` phụ kiện, `M` bản đồ, `U` waypoint |
| Khác | `K` bật tắt shader, `F6` / `F7` nhận / từ chối lời mời raid, `L` advancement |

Phím vanilla giữ mặc định. Phím debug của Cobblemon, phím mở màn hình config và vài phím ít dùng (Ultra Burst, phóng to minimap, terminal của Tom's Storage, Social Interactions) không gán phím. Sửa bố cục trong `LAYOUT` của `tools/pack/keybinds.py`, rồi chạy lại `./build.sh`.

## Server

Server chạy bằng [itzg/minecraft-server](https://github.com/itzg/docker-minecraft-server). Image tự cài pack từ `dist/latest.mrpack` và cài lại khi file pack đổi.

```sh
cd server
docker compose up -d                  # server chơi, dữ liệu ở server/data
docker exec -it cobbleverse rcon-cli  # console
```

Server mặc định chỉ nghe trên `127.0.0.1:25565`. Để bạn bè vào được, tạo `server/.env`:

```
BIND=0.0.0.0
MEMORY=8G
```

`server/compose.test.yaml` là server test có thêm mod Carpet, dữ liệu để ở `server/data-test`. Carpet tạo người chơi giả, nhờ vậy Pokémon spawn được khi không có client:

```sh
docker compose -f compose.test.yaml up -d
docker exec cobbleverse-test rcon-cli player Bot spawn
```

## Công cụ kiểm tra

- `tools/inspect/linkcheck.py` liệt kê các class, method, field của Cobblemon mà một jar gọi tới nhưng jar Cobblemon đích không có.
- `tools/inspect/deps.py` in phần `depends` trong `fabric.mod.json` của bản đang dùng và bản mới nhất.
- `tools/inspect/spawn_diff.py` và `tools/inspect/fork_changes.py` so file spawn giữa Cobblemon 1.7.3, 1.8.4 và COBBLEVERSE.
- `tools/inspect/keyscan.py` tìm tên keybinding trong các jar.
- `tools/inspect/mixins.py` in danh sách mixin của một jar.
- `tools/client/trylaunch.sh` mở profile ở chế độ offline qua XWayland, chờ load xong, bấm F2 bằng `xdotool`, lưu ảnh vào `build/client-tests/` rồi tắt game. Đặt `QUICKPLAY=<tên world>` để vào thẳng một world.
- `tools/client/bisect.sh` bật tắt từng nhóm mod trong profile. `tools/client/bisect_rp.py` chia đôi resource pack tự động, so ảnh F2 với một ảnh splash bị kẹt.

## Cập nhật

1. Đổi phiên bản trong `port.json`. Mỗi mod ghi `[version_number, version_id]` lấy từ Modrinth. `build.py` báo lỗi nếu hai giá trị không khớp nhau.
2. Chạy `./build.sh` rồi đọc `build/merge.log`.
3. Kiểm tra server bằng `compose.test.yaml` và client bằng `tools/client/trylaunch.sh`.

Khi COBBLEVERSE ra bản chính thức cho 1.8, world tạo bằng bản port này có thể không chuyển sang được, vì bản chính thức có thể bỏ hoặc đổi mod khác đi. Nên backup `server/data` trước khi đổi pack.

## Lỗi đã biết

- Một spawn Hoopa trong ATM x MSD trỏ tới preset `end_city` không tồn tại, server bỏ qua spawn đó.
- Block `mega_showdown:wishing_star_crystal` trong vài công trình mất hướng đặt, vì Mega Showdown 1.3 bỏ thuộc tính `facing`.
- Log báo `Unable to apply dex addition cobblemon:mega_z`. Lỗi này có cả trong COBBLEVERSE gốc.
