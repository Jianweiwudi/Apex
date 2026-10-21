# Apex

用於 **Assetto Corsa Competizione** 的桌面工具：抓地力調整、碰撞無車損、HUD 疊加層、賽段與加油計算，
以及一支可替換成遊戲片頭的 3D 開場動畫。

介面是本機的 WebView2 面板（Apex.exe 只負責開視窗），實際工作由兩個地方完成：面板裡的 HTML/JS，
和一個在 127.0.0.1:7798 監聽的小型 Python 服務（grip/apex_grip_server.py，負責讀寫 ACC 行程、掃描安裝路徑、
管理片頭檔案）。HUD 則是另一個獨立程式 ApexOverlay.ps1（GDI+ 分層視窗，透過 127.0.0.1:7799 受面板控制）。

---

## 功能

| 功能 | 說明 |
|---|---|
| **抓地力倍率** | 直接把輪胎模型的 22 條 × 21 點曲線依倍率改寫進 ACC 記憶體（1.00–1.20）；換 setup、重進賽道會自動重貼 |
| **碰撞無車損** | 改寫 ACC 已載入的 damageRate，撞擊後約 1 秒自動修復；可隨時關閉 |
| **HUD 疊加層** | S / M / L 三種尺寸、可鎖定、可隱藏；顯示檔位、速度、G 值、油量、單圈 |
| **四輪胎況** | 四輪熱胎壓力（psi）與胎芯溫度（°C）即時顯示，溫度分級上色，另給溫差與平均胎壓 |
| **圈速** | 當前圈（本地插值，逐幀走）、上一圈、最佳，Δ 上色，最近 10 圈折線 |
| **賽段與加油** | 讀單圈時間與每圈油耗，算出剩餘圈數與建議加油量 |
| **開場動畫** | 內建 1080p60 的 3D 開場片，可一鍵換成 ACC 啟動片頭；原廠檔案自動備份，可還原 |
| **匯入自己的片頭** | 任何影片（mp4/mkv/mov/avi/webm/wmv…）自動轉成 1080p60 WMV2，長度對齊原廠 72.22 秒；比原廠短會溶接到「按任意鍵繼續」卡片，比原廠長會在最尾一秒影音同步淡出 |
| **片頭音量** | 0–200 %，可用滑桿或滾輪（每格 1 %）調整；只重寫音軌、畫面不動 |
| **畫質選項** | 逐項開關：陰影、體積霧、螢幕空間反射、泛光、動態模糊、環境光遮蔽、抗鋸齒；寫入 `Scalability.ini`（覆寫 0–4 各級）與 `Engine.ini`，改前備份、全關時逐位元組還原 |

---

## 需求

- Windows 10 / 11 x64
- **Microsoft Edge WebView2 Evergreen Runtime**（面板是 WebView2 宿主；缺少會白屏）
- **Python 3.8+**（抓地力後端）。找不到時可設環境變數 APEX_PY 指向 pythonw.exe
- Assetto Corsa Competizione（Steam 版會自動偵測；其他版本可在面板手動指定資料夾）

---

## 安裝

1. 把整個資料夾解壓到任意位置（路徑可含空格與中文）。
2. 第一次使用（或搬移過資料夾）**雙擊 setup.cmd**：
   - 註冊「Apex Grip Watchdog」排程工作（登入時 + 每 5 分鐘；只在後端沒回應時才啟動它）
   - 執行環境檢查，逐項列出 PASS / FAIL / INFO，結果存到 tools\_doctor.log
3. 之後照常使用桌面「Apex」捷徑即可（捷徑指向 ApexLauncher.ps1，它會先確認後端就緒再開面板）。

> 直接開 Apex.exe 也能用：看門狗會在 5 分鐘內把後端補上，面板每 3 秒輪詢，後端回來就自動恢復。

---

## 目錄結構

```
Apex/
  Apex.exe                     WebView2 面板宿主
  Apex.vbs                     ｜無控制台啟動（桌面捷徑指向它）
  ApexOverlay.vbs              ｜
  ApexGrip.vbs / -Stop.vbs     ｜
  ApexLauncher.ps1             啟動器（確認後端 → 開面板）
  ApexGrip.cmd                 找 Python 並啟動後端
  ApexGrip-Stop.cmd            停止後端
  ApexOverlay.cmd / .ps1       HUD 疊加層
  setup.cmd                    一次性設定＋環境檢查
  SETUP.txt                    同樣內容的純文字版
  grip/
    apex_grip_server.py        抓地力／車損／片頭 的本機服務（127.0.0.1:7798）
    grip_curves.json           輪胎曲線資料
  ui/
    index.html                 面板介面（含 i18n：繁中／簡中／英文）
    media/                     開場動畫（mp4 預覽 / wmv 給 ACC / 封面）
  tools/
    apex_doctor.ps1            環境檢查
    grip_watchdog.ps1          後端看門狗
    install_watchdog.ps1       重新綁定看門狗到目前路徑
    get_ffmpeg.ps1             下載 ffmpeg（只有「匯入影片」需要）
    ffmpeg/                    下載後放在這裡，不進版控
```

---

## 開場動畫

內建一支 12 秒的 3D 開場片（1920×1080、60 fps），之後接一張「按任意鍵繼續」卡片，整支影片長度
**72.22 秒**——與 ACC 原廠片頭等長，所以遊戲不會等不到時長而卡在最後一幀。

### 換成自己的影片

面板的「啟動動畫」區塊有 **匯入我的影片…**：

1. 點它會跳出系統的開檔對話框，選任何常見影片（mp4 / mkv / mov / avi / webm / wmv…）。
2. 後端會自動轉成 ACC 能播的形狀：**1920×1080、60 fps、WMV2 + WMAV2 / ASF**。
3. 長度自動對齊原廠：比 72.22 秒長就裁掉，比較短就用**最後一幀延展**補滿（不會變黑場）。
4. 畫面比例不合就等比縮放加黑邊（不裁切、不變形）；沒有聲音的來源會補靜音軌。
5. 換上去之前會先把目前片頭備份成 `ACC_GameIntro_1.1_16-9.wmv.apex.bak`，隨時可「還原原廠」。

轉檔需要 ffmpeg。第一次用之前執行一次：

```bat
powershell -ExecutionPolicy Bypass -File tools\get_ffmpeg.ps1
```

它會把 ffmpeg.exe 抓到 `tools\ffmpeg\`（約 88 MB，不進版控）；也可以在系統 PATH 裡已經有 ffmpeg。

---

## 疑難排解

| 症狀 | 先看 |
|---|---|
| 面板顯示「後端未運行」 | tools\_grip_start.log（用了哪個 Python）、tools\_grip_watchdog.log（有沒有被補啟動） |
| 面板白屏 | 缺 WebView2 Runtime（setup.cmd 會標 FAIL） |
| 找不到 ACC | 面板的「啟動動畫」區塊可手動指定資料夾 |
| Windows 顯示 SmartScreen 警告 | 執行檔未簽章，屬正常；選「仍要執行」 |
| 匯入時說缺少 ffmpeg | 執行 `tools\get_ffmpeg.ps1`，或把 ffmpeg.exe 放進 `tools\ffmpeg\` |
| 遊戲裡片頭不是新的 | apex_doctor.ps1 會比對遊戲內檔案與 ui\media\apex_intro.wmv 是否一致；不一致就在面板重新套用 |

後端狀態可直接看：http://127.0.0.1:7798/status

---

## 授權

見 `LICENSE`（**Apex Licence 1.2**，正體中文與英文並列）。重點：

- **僅限個人、非商業、離線單機使用**；不得用於線上多人對局、線上賽事平台或任何收費用途。
- 本工具會**直接讀寫遊戲記憶體**，帳號風險與後果由使用者自行承擔。
- **使用者自行匯入的影片不在散布範圍內**；使用者必須自行確認其影片的權利（著作權、音樂授權等）。
- 本工具不連網、不收集、不上傳任何資料；設定與日誌只留在本機。

第三方程式與商標（WebView2、FFmpeg、Windows 字型、ACC 商標）見 `THIRD-PARTY-NOTICES.md`。