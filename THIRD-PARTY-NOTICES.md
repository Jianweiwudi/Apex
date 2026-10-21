# Third-Party Notices

Apex 本身以 Apex Licence 1.2 釋出（見 `LICENSE`）。它使用或引用下列第三方程式／資源；
以下元件**不隨本專案散布**，由使用者系統或使用者自行下載提供。

## Microsoft Edge WebView2 Runtime

- 用途：面板（`Apex.exe` 是 WinForms + WebView2 宿主）的瀏覽器執行環境。
- 取得方式：由 Windows 或 Microsoft 官方安裝程式提供，本專案不附帶。
- 授權：Microsoft 的 WebView2 Runtime 授權條款。
- 專案內隨附的 `Microsoft.Web.WebView2.Core.dll`、`Microsoft.Web.WebView2.WinForms.dll`、
  `WebView2Loader.dll` 為 WebView2 SDK 的組件，依其原始授權使用。

## FFmpeg

- 用途：僅「匯入我的影片」功能需要，用於把使用者提供的影片轉成遊戲可播放的 WMV2/WMAV2/ASF。
- 取得方式：`tools\get_ffmpeg.ps1` 由使用者自行下載到 `tools\ffmpeg\`，**不進版控、不隨專案散布**。
- 授權：FFmpeg 專案（LGPL 2.1+ / GPL，視建置選項而定），著作權屬 FFmpeg 開發者。

## 字型

- Bahnschrift、Microsoft JhengHei（微軟正黑體）、Segoe UI：Windows 內建字型，用於介面與片頭字卡。
- **不隨本專案散布**；未內嵌任何字型檔。

## Assetto Corsa Competizione

- 本工具為 ACC 的**非官方**第三方輔助程式，與 Kunos Simulazioni、505 Games 無隸屬、贊助或背書關係。
- `Assetto Corsa Competizione`、`ACC` 等名稱為其各自權利人的商標。
- 本專案**不含**任何遊戲本體檔案；片頭替換只在使用者本機複製檔案，並保留原檔備份（`.apex.bak`）。

## 共享記憶體佈局

- `grip/apex_grip_server.py` 讀取 ACC/AC 的 shared memory 結構（`SPageFilePhysics`、
  `SPageFileGraphic`、`SPageFileStatic`）。欄位配置參考社群的公開文件與逆向整理，屬事實性資料。

## 其他

- 輪胎曲線資料 `grip/grip_curves.json` 取自遊戲執行時讀出的資料，僅供本工具在本機使用。
- 專案內的示範片頭（`ui/media/apex_intro.*`、`card_loop.mp4`）由本專案自行製作。
