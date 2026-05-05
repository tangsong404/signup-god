# signup-god

可插拔的邮箱注册编排框架。

目前支持：

- 依赖 DuckDuckGo Email Protection私密邮箱 为 QQ邮箱 起别名创建大量账号，自动接收验证码并注册 Deepseek 账号

## 项目结构

项目把"批量注册一个站点的账号"拆成三类可单独替换的组件：

| 组件 | 职责 | 
| --- | --- | 
| `account_generators/` | 生产新账号的标识（邮箱 / 用户名 / 别名……） |
| `checkcode/` | 提供验证码（人工 / 邮箱 / 短信……）|
| `registrars/` | 站点注册器，把以上两者编排成一次完整注册流程  |

未来要支持其他站点 / 邮箱 / 邮箱供应商，分别在对应包下加子模块即可，三层之间互不耦合。

## 快速开始

要求 Python 3.11+，请科学上网后使用此库，在美国节点效果最好

```powershell
cd signup-god
pip install -e ".[dev]"   # 把 account_generators / checkcode / registrars 三个顶层包装到当前 Python 环境
copy .env.example .env    # 然后按下面的说明把 4 个变量填上你自己的值
python main.py            # 等价于 --num 1
python main.py --num 5    # 批量注册 5 个账号
```


## .env 配置

### 选哪些组件（可选，全部有默认值）

`main.py` 启动时按下面三个变量从内置注册表里挑出对应实现，每项不写就用默认。

| 变量 | 默认值 | 现有可选值 | 说明 |
| --- | --- | --- | --- |
| `SIGNUP_REGISTRAR` | `deepseek` | `deepseek` | 注册器（站点） |
| `SIGNUP_CHECKCODE` | `qq_mail` | `qq_mail`、`manual` | 验证码源（`manual` 走命令行手输） |
| `SIGNUP_ACCOUNT_GENERATOR` | `duck_email` | `duck_email` | 账号 ID 生成器 |

要新增一项就在 `main.py` 里 `REGISTRARS` / `CHECKCODE_SOURCES` / `ACCOUNT_GENERATORS` 三个 dict 里加一个键值即可。

### 各组件需要的密钥/参数

只有被你选中的那个组件对应的变量才必须填；其余可以留空或删除。

| 变量 | 谁用 | 怎么拿 |
| --- | --- | --- |
| `DEEPSEEK_DEVICE_ID` | `registrar=deepseek` | 浏览器打开 [chat.deepseek.com](https://chat.deepseek.com)，控制台执行 `await window.SMSdk?.getDeviceId?.()`，整串复制过来 |
| `DEEPSEEK_REGISTER_PASSWORD` | `registrar=deepseek`（同时是给所有新账号设的密码） | 自己定，10 位以上即可 |
| `QQ_MAIL_COOKIE` | `checkcode=qq_mail` | 浏览器登录 [wx.mail.qq.com](https://wx.mail.qq.com)，F12 → Network → 任选一条 `/list/maillist` → Copy as cURL，把 `Cookie:` 后的整串拿过来 |
| `DUCK_EMAIL_API_TOKEN` | `account_generator=duck_email` | 在 Duck.ai 浏览器扩展登录后，从扩展存储里能取到；或参考 `duckduckgo-email-autofill` 的截获方式 |

> 看到 `qq api /list/maillist ret=-20002` 就刷新 Cookie。看到 `RISK_DEVICE_DETECTED` 就更新 DeepSeek 的 device_id。

## 运行流程

以QQ邮箱作验证器批量注册 Deepseek 的账号为例：

`python main.py --num N` 会：

1. 启动 QQ 监听子进程，拉一次 `/list/maillist` 作 baseline；
2. 通过 `DuckEmailAccountGenerator` 申请一个新的 `xxx@duck.com`；
3. 调 DeepSeek `create_email_verification_code`（含 Guest PoW），触发邮件；
4. 监听器轮询 baseline 之后的新邮件，按 `DeepSeekRegistrar.mail_match_criteria()` 给的 sender / subject / 6 位数字正则提取验证码，并把这封邮件删掉；
5. 调 `register`（再做一次 PoW）→ 调 `set_birthday`（随机年月）；
6. 把成功的 `(identifier, password, token="")` 一行追加到 `结果.csv`（UTF-8 BOM，Excel 可直接打开）；
7. 当前账号成功后，等 `max(0, 60 - 本轮耗时)` 秒再开下一个，节流为「每 60 秒一个账号」（最后一个账号不等）。

每个账号结束都会打印：

```
-----3/5, this run elapsed 31.42s, total elapsed 153.07s-----
```

失败的账号不写入 `结果.csv`，整个进程返回非 0 退出码。

## 单条手动注册（供调试）

如果 QQ 监听没接通、想直接手动塞验证码：

```powershell
python -m registrars.deepseek register --email you@example.com --password "Pa$$w0rd!"
```

会启动 `ManualCheckcodeSource`，命令行交互式让你贴验证码。

## 测试

```powershell
python -m pytest -q
```

40+ 测试覆盖：DeepSeekHashV1 / SolvePow 黄金向量、注册器 HTTP mock、QQ 监听子进程协议、配置解析、CheckcodeSource 协议契约等。注意全部测试都不会真实联网，可以离线跑。

## 扩展指南

### 加一个新站点的注册器

1. 新建 `src/registrars/<site>/`，至少实现：

   ```python
   from checkcode.mail_match import MailMatchCriteria

   class FooRegistrar:
       @staticmethod
       def mail_match_criteria() -> MailMatchCriteria:
           return MailMatchCriteria(
               sender_keyword="foo",
               subject_keywords=("Foo", "verification"),
               code_regex=r"(?<![0-9])([0-9]{6})(?![0-9])",
           )

       def __init__(self, *, checkcode_source, config, http_client=None) -> None: ...
       def init(self) -> None: ...
       def close(self) -> None: ...
       def register_one(self, *, identifier: str, password: str) -> None: ...
   ```

2. 在 `main.py` 的 `REGISTRARS` dict 里加一行（写好 `build` 和 `register_one`），完事。

`QQMailCheckcodeSource` 看到这个 `mail_match_criteria()` 就会自动按你给的 sender / subject / 正则去匹配；你完全不用动 `checkcode/` 目录的任何代码。

### 加一个新的验证码源

1. 实现 `checkcode.base.CheckcodeSource` Protocol（`init()` / `close()` / `receive_code(email, *, timeout_sec)`），放在 `src/checkcode/<thing>/source.py`。如果它也是基于邮件的，可以复用 `MailMatchCriteria` 把"哪些邮件归我"的判定推给注册器。
2. 在 `main.py` 的 `CHECKCODE_SOURCES` dict 里加一行：`"<name>": <build_func>`，`build_func(*, registrar_cls)` 负责构造实例。

### 加一个新的账号生成器

1. 实现 `account_generators.base.AccountIdentifierGenerator`（`next_identifier() -> str`），放在 `src/account_generators/<thing>.py`。
2. 在 `main.py` 的 `ACCOUNT_GENERATORS` dict 里加一行：`"<name>": <build_func>`，`build_func(*, http_client)` 负责构造实例。

## 已知限制

- 只支持 Python 3.11+。
- QQ 邮箱 Cookie 一旦被服务端清掉（一两天），需要手动刷新。
- DeepSeek 的 `device_id` 同样是临时性的，被风控判定为 `RISK_DEVICE_DETECTED` 时需要重新到浏览器里取一次。
- DuckDuckGo 私密邮箱有总数上限（账户级，几千个），不要无限调用。
