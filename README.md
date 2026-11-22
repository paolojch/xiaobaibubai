# 小白不白 (xiaobaibubai)

一只住进你电脑桌面角落的黑猫互动桌面宠物——支持 **Windows** 与 **macOS** 双平台，**免安装双击直接运行**。当你在电脑上写代码、聊天、浏览网页或打游戏时，**小白不白**会实时同步敲击 60% 机械键盘、滑动小桌鼠、3D 转头追随光标，发呆久了还会偷偷低头舔爪爪。

---

## 核心功能亮点

- **全键盘实时响应 & 60% 机械键盘下沉**
  - 61 颗独立 3D 斜角键帽搭配橙色功能键点缀；你在任何窗口打字时，小白不白左右猫爪会就近伸出敲击对应键帽，键帽产生真实物理下沉与荧光绿高光反馈。
- **猫实时按键气泡 & 桌面按键浮窗**
  - 打字时小猫胸前上方会实时弹出极简按键气泡（支持 `␣`、`↵`、`⇧`、`⌫`、`⌘` 等按键符号），也可按需在右键菜单中开启屏幕底部悬浮键帽条。
- **360° 正面 3D 头部透视与鼠标追随**
  - 鼠标在桌面移动或绕着猫头转圈时，不只是双眸瞳孔跟随，整个猫头、双耳与胡须也会产生细腻的正面 3D 偏航与俯仰；边滑鼠标边单手敲键时自动切换为「左爪滑鼠 + 右爪敲键」。
- **长待机抬爪舔毛动作**
  - 静置待机约 15 秒后，小猫会自然进入理毛状态：抬起前爪伸出粉色小舌头绕爪背划弧舔舐，头部随之柔和一低一抬。
- **摸头闭眼与星光互动**
  - 左键轻点猫头即可触发开心弯月眯眼与星光反馈。
- **内置多种机械轴音效 & 透明穿透**
  - 默认内置 `Holy Panda`、`Alpaca`、`Cherry MX Blue ABS`、`Ink Black` 机械轴按键音与微动鼠标音，支持透明置顶、一键开启鼠标穿透与自由调节尺寸（`196px ~ 640px`）。

---

## 免安装快速使用

前往 [Releases 最新版本页面](https://github.com/paolojch/xiaobaibubai/releases/latest) 直接下载对应系统安装包，**无需安装 Python 或任何运行环境**：

| 平台 | 下载文件 | 使用方式 |
| --- | --- | --- |
| **Windows (10 / 11 64位)** | [xiaobaibubai-Windows.exe](https://github.com/paolojch/xiaobaibubai/releases/latest/download/xiaobaibubai-Windows.exe) | 下载后直接双击运行即可 |
| **macOS (Apple Silicon / Intel)** | [xiaobaibubai-macOS.dmg](https://github.com/paolojch/xiaobaibubai/releases/latest/download/xiaobaibubai-macOS.dmg) / [.zip](https://github.com/paolojch/xiaobaibubai/releases/latest/download/xiaobaibubai-macOS.zip) | 拖入「应用程序」或解压后双击 `xiaobaibubai.app` |

### 首次运行系统授权提示
- **Windows**：若首次运行弹出 *Microsoft Defender SmartScreen* 保护提示，点击 **「更多信息」→「仍要运行」** 即可。
- **macOS**：
  1. 若首次提示“无法验证开发者”，请在 `xiaobaibubai.app` 上**右键点击 → 选择「打开」**放行；
  2. 为确保切到其他应用打字和移动鼠标时也能同步响应，请在 **「系统设置 → 隐私与安全性 → 辅助功能 / 输入监控」** 中勾选允许 `xiaobaibubai`。

---

## 交互与右键设置菜单

- **左键拖拽**：将小猫自由拖放到桌面任意角落，位置会在退出时自动记忆保存。
- **滚轮 / 右键菜单**：快速调整宠物尺寸大小与窗口透明度。
- **右键小猫 / 系统托盘图标**：
  - 开关 **「猫实时按键气泡」**、屏幕键帽浮窗（Keycap HUD）、敲击星光粒子
  - 开关 **「窗口始终置顶」** 与 **「鼠标穿透模式」**（开启穿透后可直接从托盘右键菜单还原）
  - 切换机械轴体音色包、调节音量或切换静音陪伴模式

---

## 从源码运行与自行打包

### 1. 本地源码运行
需要 Python `3.11+`：

```bash
pip install -r requirements.txt
python src/main.py
```

### 2. 运行测试套件
```bash
python -m unittest discover -s tests -v
```

### 3. 一键打包当前系统独立包
```bash
pip install pyinstaller
python build_release.py
```
- 在 Windows 下生成：`dist/xiaobaibubai-Windows.exe`
- 在 macOS 下生成：`dist/xiaobaibubai.app`、`dist/xiaobaibubai-macOS.dmg` 与 `dist/xiaobaibubai-macOS.zip`

---

## 目录结构

```text
.
├── .github/workflows/release.yml   # Windows & macOS 双平台自动化编译与发布工作流
├── assets/
│   ├── frames/                     # 基准参考帧序列
│   ├── parts/                      # 拆解后的猫咪部件图层与锚点配置
│   └── sounds/                     # 机械键盘轴体与鼠标微动音频包
├── src/
│   ├── main.py                     # 应用入口、全局钩子调度与系统托盘
│   ├── config.py                   # 跨平台配置与打包资源路径管理
│   ├── input_hook.py               # Windows (ctypes) & macOS (pynput) 全局键鼠监听
│   ├── state_machine.py            # 猫咪姿态、手臂动力学、舔爪与 3D 注视状态机
│   ├── rig.py                      # 60% 机械键盘、五官、胡须、舔爪与猫爪程序化绘制
│   ├── pet_window.py               # 透明无边框置顶窗体与右键设置菜单
│   ├── keycap_hud.py               # 屏幕悬浮按键提示条
│   └── sound_engine.py             # 音频预加载与实时混音播放引擎
├── tests/                          # 资产校验、状态机动力学、音效与 UI 冒烟测试
├── build_release.py                # 跨平台 PyInstaller 打包脚本
└── requirements.txt                # 运行依赖声明
```

---

## 致谢与音频许可

内置开源机械键盘与鼠标音效采自 MIT 许可音效集合，完整归属说明见 [assets/sounds/LICENSE.txt](assets/sounds/LICENSE.txt)。
