# aiphone — 把普通手机变成 AI 手机

结构：**大脑 + 可插拔的手**。大脑负责理解、记忆、规划（MVP 阶段由 Claude 充当，后续接 dw_agent_world）；手负责看屏幕、点按、输入。

- `hand-android/`：安卓「手」——无障碍服务 App，长轮询大脑取指令（observe / screenshot / tap / swipe / click_text / type / global / launch / open_url / apps）。
- `brain/hub.py`：大脑与手之间的中转站（标准库，端口 8700），`/hand/poll`、`/hand/result` 给手用，`/cmd` 仅本机可调。
- `brain/phone.py`：大脑侧命令行，`phone.py observe` / `tap` / `click` / `type` …

## 跑起来

```bash
python3 brain/hub.py                         # 启动中转，打印配对码
cd hand-android && ./gradlew assembleDebug   # 出包：app/build/outputs/apk/debug/app-debug.apk
```

手机装 APK → 填服务器地址和配对码 → 系统无障碍里打开「AI 手」→ 状态显示「已连上大脑」。

## 已知边界

- 鸿蒙 6 原生 App 不能被第三方代点；本 App 在鸿蒙上只能装进卓易通，操作卓易通里的安卓 App（待实测）。
- 微信、支付宝、银行等明确拒绝 AI 代操作，不去碰。
