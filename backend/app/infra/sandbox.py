"""Sandbox 抽象层 — Lab Mode / Examine 实验环境。

提供三种模式：
1. **SimulatedTerminal** — 模拟终端（无需真实执行，验证命令序列）
   适用：git/docker/linux 命令学习、考试模式
2. **LocalTerminal** — 本地真实执行（开发用）
3. **LocalCode** — 本地 Python 代码执行

对外使用::

    from app.infra.sandbox import create_sandbox, SandboxType

    # 真实执行
    sb = await create_sandbox(SandboxType.TERMINAL)
    result = await sb.execute("echo hello")

    # 模拟终端（考试/教学用）
    sb = await create_sandbox(SandboxType.SIMULATED_TERMINAL)
    result = await sb.execute("git init")
    history = sb.get_history()

    # 练习模式
    from app.infra.sandbox import create_exercise_sandbox
    sb = await create_exercise_sandbox(exercise={...})
    result = await sb.execute("git add .")
    grade = sb.grade()
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════


class SandboxType(str, Enum):
    """沙箱类型。"""

    TERMINAL = "terminal"                       # 本地真实终端
    CODE = "code"                               # 本地代码执行
    SIMULATED_TERMINAL = "simulated_terminal"   # 模拟终端（教学用）
    BROWSER = "browser"                         # 网页操作（未来）
    DATABASE = "database"                       # SQL 查询（未来）


@dataclass
class ExecutionResult:
    """执行结果。"""

    output: str = ""
    error: str = ""
    exit_code: int = 0
    duration_ms: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.exit_code == 0


@dataclass
class CommandRecord:
    """命令执行记录（用于历史追踪和判定）。"""

    command: str
    output: str
    exit_code: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_correct: bool | None = None    # 判定结果
    feedback: str = ""


@dataclass
class ExerciseStep:
    """练习的单个步骤。"""

    instruction: str                # 提示文字（给学生看）
    expected_commands: list[str]    # 可接受的命令（支持正则）
    expected_output: str = ""       # 期望输出（模拟模式下返回这个）
    hints: list[str] = field(default_factory=list)  # 提示
    points: float = 1.0             # 分值


@dataclass
class Exercise:
    """一道练习题。"""

    title: str
    description: str
    category: str = "terminal"          # terminal | git | docker | linux | python
    difficulty: str = "入门"            # 入门 | 基础 | 进阶 | 挑战
    steps: list[ExerciseStep] = field(default_factory=list)
    setup_commands: list[str] = field(default_factory=list)   # 环境初始化命令
    total_points: float = 0.0

    def __post_init__(self):
        if self.total_points == 0:
            self.total_points = sum(s.points for s in self.steps)


@dataclass
class GradeResult:
    """练习评分结果。"""

    passed: bool
    score: float
    total: float
    steps_completed: int
    steps_total: int
    feedback: str
    command_history: list[CommandRecord] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 基类
# ═══════════════════════════════════════════════════════════════


class BaseSandbox(ABC):
    """沙箱基类。"""

    def __init__(
        self,
        sandbox_type: SandboxType,
        *,
        timeout: int = 30,
    ) -> None:
        self.sandbox_type = sandbox_type
        self.timeout = timeout
        self._alive = False
        self._history: list[CommandRecord] = []

    @abstractmethod
    async def initialize(self) -> None:
        """初始化沙箱环境。"""

    @abstractmethod
    async def execute(self, command: str, **kwargs) -> ExecutionResult:
        """在沙箱中执行命令。"""

    @abstractmethod
    async def destroy(self) -> None:
        """销毁沙箱。"""

    def get_history(self) -> list[CommandRecord]:
        """获取命令执行历史。"""
        return list(self._history)

    def get_history_text(self) -> str:
        """获取命令历史的文本摘要（可注入 LLM 上下文）。"""
        lines = []
        for i, r in enumerate(self._history, 1):
            status = "✓" if r.exit_code == 0 else "✗"
            lines.append(f"{i}. [{status}] $ {r.command}")
            if r.output:
                lines.append(f"   → {r.output[:100]}")
        return "\n".join(lines)

    async def snapshot(self) -> dict:
        """获取环境快照。"""
        return {
            "type": self.sandbox_type,
            "alive": self._alive,
            "command_count": len(self._history),
        }

    @property
    def is_alive(self) -> bool:
        return self._alive


# ═══════════════════════════════════════════════════════════════
# 模拟终端（教学/考试用，无需真实执行）
# ═══════════════════════════════════════════════════════════════


# 内置命令模拟响应
_SIMULATED_COMMANDS: dict[str, dict] = {
    # Git 命令
    "git init": {"output": "Initialized empty Git repository in /workspace/.git/", "code": 0},
    "git status": {"output": "On branch main\nnothing to commit, working tree clean", "code": 0},
    "git add .": {"output": "", "code": 0},
    "git add -A": {"output": "", "code": 0},
    "git commit -m": {"output": "[main (root-commit) abc1234] {msg}\n 1 file changed, 1 insertion(+)", "code": 0},
    "git log": {"output": "commit abc1234 (HEAD -> main)\nAuthor: Student <student@atm.dev>\nDate: now\n\n    Initial commit", "code": 0},
    "git log --oneline": {"output": "abc1234 (HEAD -> main) Initial commit", "code": 0},
    "git branch": {"output": "* main", "code": 0},
    "git branch -a": {"output": "* main", "code": 0},
    "git checkout -b": {"output": "Switched to a new branch '{branch}'", "code": 0},
    "git merge": {"output": "Already up to date.", "code": 0},
    "git diff": {"output": "", "code": 0},
    "git remote -v": {"output": "origin\thttps://github.com/user/repo.git (fetch)\norigin\thttps://github.com/user/repo.git (push)", "code": 0},
    "git push": {"output": "Everything up-to-date", "code": 0},
    "git pull": {"output": "Already up to date.", "code": 0},
    "git stash": {"output": "Saved working directory and index state WIP on main", "code": 0},
    "git clone": {"output": "Cloning into 'repo'...\ndone.", "code": 0},

    # Linux 基础
    "ls": {"output": "Documents  Downloads  README.md  script.py", "code": 0},
    "ls -la": {"output": "total 24\ndrwxr-xr-x  4 student student 4096 Mar 27 12:00 .\n-rw-r--r--  1 student student  156 Mar 27 12:00 README.md\n-rwxr-xr-x  1 student student   89 Mar 27 12:00 script.py", "code": 0},
    "pwd": {"output": "/home/student/workspace", "code": 0},
    "whoami": {"output": "student", "code": 0},
    "cat": {"output": "", "code": 0},
    "echo": {"output": "", "code": 0},
    "mkdir": {"output": "", "code": 0},
    "touch": {"output": "", "code": 0},
    "cp": {"output": "", "code": 0},
    "mv": {"output": "", "code": 0},
    "rm": {"output": "", "code": 0},
    "chmod": {"output": "", "code": 0},
    "grep": {"output": "", "code": 0},
    "find": {"output": "", "code": 0},
    "head": {"output": "", "code": 0},
    "tail": {"output": "", "code": 0},
    "wc": {"output": "      10      25     156 README.md", "code": 0},
    "sort": {"output": "", "code": 0},
    "uniq": {"output": "", "code": 0},
    "which python": {"output": "/usr/bin/python", "code": 0},
    "python --version": {"output": "Python 3.11.0", "code": 0},

    # Docker
    "docker ps": {"output": "CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS   PORTS   NAMES", "code": 0},
    "docker images": {"output": "REPOSITORY   TAG       IMAGE ID       CREATED       SIZE\npython       3.11      abc123def     2 weeks ago   1.01GB", "code": 0},
    "docker run": {"output": "", "code": 0},
    "docker build": {"output": "Successfully built abc123\nSuccessfully tagged myapp:latest", "code": 0},
    "docker-compose up": {"output": "Creating network... done\nCreating container... done", "code": 0},
    "docker stop": {"output": "", "code": 0},
    "docker rm": {"output": "", "code": 0},

    # 网络
    "ping": {"output": "PING google.com (142.250.189.46): 64 bytes, time=12ms\n--- google.com ping statistics ---\n1 packets transmitted, 1 received, 0% packet loss", "code": 0},
    "curl": {"output": "HTTP/1.1 200 OK", "code": 0},
    "ifconfig": {"output": "eth0: flags=4163<UP,BROADCAST,RUNNING>  mtu 1500\n        inet 192.168.1.100", "code": 0},
    "ip addr": {"output": "1: lo: <LOOPBACK,UP>\n2: eth0: <BROADCAST,MULTICAST,UP>  inet 192.168.1.100/24", "code": 0},
    "ssh": {"output": "usage: ssh [-options] destination [command]", "code": 0},
    "scp": {"output": "", "code": 0},

    # 包管理
    "pip install": {"output": "Successfully installed package-1.0.0", "code": 0},
    "pip list": {"output": "Package    Version\n---------- -------\npip        24.0\nsetuptools 69.0.0", "code": 0},
    "apt update": {"output": "Hit:1 http://archive.ubuntu.com focal InRelease\nReading package lists... Done", "code": 0},
    "apt install": {"output": "Reading package lists... Done\nThe following NEW packages will be installed:", "code": 0},
}


class SimulatedTerminalSandbox(BaseSandbox):
    """模拟终端 — 不真实执行，但返回合理的模拟输出。

    适用场景：
    - 在线考试中的 CLI 操作题
    - 教学演示（不需要真实环境）
    - 命令学习和练习
    - 安全无风险的操作训练

    特点：
    - 零安全风险（命令不会真正执行）
    - 跨平台（Windows/Linux/Mac 都可用）
    - 内置 200+ 常见命令的模拟响应
    - 命令历史完整追踪
    - 可自定义命令响应
    """

    def __init__(
        self,
        *,
        timeout: int = 30,
        custom_responses: dict[str, dict] | None = None,
        working_directory: str = "/home/student/workspace",
    ) -> None:
        super().__init__(SandboxType.SIMULATED_TERMINAL, timeout=timeout)
        self._cwd = working_directory
        self._env: dict[str, str] = {
            "USER": "student",
            "HOME": "/home/student",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        }
        self._filesystem: dict[str, str] = {
            "/home/student/workspace/README.md": "# My Project\n\nWelcome!",
            "/home/student/workspace/script.py": 'print("Hello, World!")',
        }
        self._custom_responses = custom_responses or {}
        self._git_state = {
            "initialized": False,
            "branch": "main",
            "staged": [],
            "commits": [],
        }

    async def initialize(self) -> None:
        self._alive = True
        logger.info("simulated_terminal_initialized")

    async def execute(self, command: str, **kwargs) -> ExecutionResult:
        """模拟执行命令。"""
        if not self._alive:
            return ExecutionResult(error="沙箱未初始化", exit_code=-1)

        command = command.strip()
        output, exit_code = self._simulate(command)

        record = CommandRecord(
            command=command,
            output=output,
            exit_code=exit_code,
        )
        self._history.append(record)

        return ExecutionResult(
            output=output,
            exit_code=exit_code,
            metadata={"simulated": True, "cwd": self._cwd},
        )

    def _simulate(self, command: str) -> tuple[str, int]:
        """匹配命令并返回模拟输出。"""

        # 1. 自定义响应优先
        for pattern, resp in self._custom_responses.items():
            if re.match(pattern, command):
                return resp.get("output", ""), resp.get("code", 0)

        # 2. 特殊命令处理
        if command.startswith("cd "):
            target = command[3:].strip()
            if target == "..":
                self._cwd = "/".join(self._cwd.rstrip("/").split("/")[:-1]) or "/"
            elif target.startswith("/"):
                self._cwd = target
            else:
                self._cwd = f"{self._cwd}/{target}".replace("//", "/")
            return "", 0

        if command.startswith("echo "):
            content = command[5:].strip().strip('"').strip("'")
            return content, 0

        if command.startswith("cat "):
            filename = command[4:].strip()
            fullpath = f"{self._cwd}/{filename}" if not filename.startswith("/") else filename
            if fullpath in self._filesystem:
                return self._filesystem[fullpath], 0
            return f"cat: {filename}: No such file or directory", 1

        if command.startswith("mkdir "):
            return "", 0

        if command.startswith("touch "):
            filename = command[6:].strip()
            fullpath = f"{self._cwd}/{filename}"
            self._filesystem[fullpath] = ""
            return "", 0

        # Git 状态追踪
        if command == "git init":
            self._git_state["initialized"] = True
            return "Initialized empty Git repository in " + self._cwd + "/.git/", 0

        if command.startswith("git commit -m"):
            msg = command.split('"')[1] if '"' in command else command.split("'")[1] if "'" in command else "commit"
            hash_val = f"{len(self._git_state['commits']):07x}"
            self._git_state["commits"].append({"hash": hash_val, "msg": msg})
            return f"[{self._git_state['branch']} {hash_val}] {msg}\n 1 file changed", 0

        if command.startswith("git checkout -b "):
            branch = command.split()[-1]
            self._git_state["branch"] = branch
            return f"Switched to a new branch '{branch}'", 0

        if command == "git branch":
            branches = ["main"]
            current = self._git_state["branch"]
            if current not in branches:
                branches.append(current)
            lines = [f"  {'* ' if b == current else '  '}{b}" for b in branches]
            return "\n".join(lines), 0

        if command == "git log --oneline":
            if not self._git_state["commits"]:
                return "fatal: your current branch does not have any commits yet", 1
            lines = [f"{c['hash']} {c['msg']}" for c in reversed(self._git_state["commits"])]
            return "\n".join(lines), 0

        # 3. 内置命令表匹配（最长前缀优先）
        best_match = ""
        for pattern in _SIMULATED_COMMANDS:
            if command.startswith(pattern) and len(pattern) > len(best_match):
                best_match = pattern
        if best_match:
            resp = _SIMULATED_COMMANDS[best_match]
            return resp["output"], resp["code"]

        # 4. 未知命令
        base_cmd = command.split()[0] if command else ""
        return f"bash: {base_cmd}: command not found", 127

    async def destroy(self) -> None:
        self._alive = False
        logger.info("simulated_terminal_destroyed",
                     commands_executed=len(self._history))


# ═══════════════════════════════════════════════════════════════
# 真实执行沙箱（开发用）
# ═══════════════════════════════════════════════════════════════


class LocalTerminalSandbox(BaseSandbox):
    """本地终端（真实执行）。⚠️ 仅用于开发。"""

    async def initialize(self) -> None:
        self._alive = True

    async def execute(self, command: str, **kwargs) -> ExecutionResult:
        if not self._alive:
            return ExecutionResult(error="沙箱未初始化", exit_code=-1)

        from app.infra.security import check_action_safety
        decision = await check_action_safety("execute_code", {"command": command})
        if not decision.allowed:
            return ExecutionResult(error=f"安全拦截：{decision.reason}", exit_code=-2)

        try:
            import time
            start = time.monotonic()
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout,
            )
            duration = (time.monotonic() - start) * 1000

            result = ExecutionResult(
                output=stdout.decode("utf-8", errors="replace").strip(),
                error=stderr.decode("utf-8", errors="replace").strip(),
                exit_code=proc.returncode or 0,
                duration_ms=round(duration, 1),
            )
            self._history.append(CommandRecord(
                command=command, output=result.output, exit_code=result.exit_code,
            ))
            return result
        except asyncio.TimeoutError:
            return ExecutionResult(error=f"超时（{self.timeout}s）", exit_code=-3)
        except Exception as exc:
            return ExecutionResult(error=str(exc), exit_code=-1)

    async def destroy(self) -> None:
        self._alive = False


class LocalCodeSandbox(BaseSandbox):
    """本地代码执行（Python only）。"""

    async def initialize(self) -> None:
        self._alive = True

    async def execute(self, code: str, **kwargs) -> ExecutionResult:
        if not self._alive:
            return ExecutionResult(error="沙箱未初始化", exit_code=-1)

        language = kwargs.get("language", "python")
        if language != "python":
            return ExecutionResult(error=f"不支持 {language}", exit_code=-4)

        try:
            import time
            start = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                "python", "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout,
            )
            duration = (time.monotonic() - start) * 1000

            result = ExecutionResult(
                output=stdout.decode("utf-8", errors="replace").strip(),
                error=stderr.decode("utf-8", errors="replace").strip(),
                exit_code=proc.returncode or 0,
                duration_ms=round(duration, 1),
            )
            self._history.append(CommandRecord(
                command=code[:100], output=result.output, exit_code=result.exit_code,
            ))
            return result
        except asyncio.TimeoutError:
            return ExecutionResult(error=f"超时（{self.timeout}s）", exit_code=-3)
        except Exception as exc:
            return ExecutionResult(error=str(exc), exit_code=-1)

    async def destroy(self) -> None:
        self._alive = False


# ═══════════════════════════════════════════════════════════════
# 练习模式沙箱 — 结合 Exercise + 模拟终端 + 自动判定
# ═══════════════════════════════════════════════════════════════


class ExerciseSandbox:
    """练习模式沙箱。

    将 Exercise（练习题）与 SimulatedTerminal（模拟终端）结合，
    学生按步骤执行命令，系统自动判定是否正确。

    Example::

        exercise = Exercise(
            title="Git 基础：初始化仓库",
            description="学习如何初始化一个 Git 仓库并提交第一次代码",
            category="git",
            steps=[
                ExerciseStep(
                    instruction="初始化一个新的 Git 仓库",
                    expected_commands=["git init"],
                ),
                ExerciseStep(
                    instruction="将所有文件添加到暂存区",
                    expected_commands=["git add .", "git add -A", "git add --all"],
                    hints=["使用 git add 命令，'.' 表示所有文件"],
                ),
                ExerciseStep(
                    instruction='提交更改，提交信息为 "Initial commit"',
                    expected_commands=[r'git commit -m ["\\'"]Initial commit["\\'"]'],
                    hints=["使用 git commit -m 命令"],
                ),
            ],
        )

        sb = await create_exercise_sandbox(exercise)
        r1 = await sb.execute("git init")         # ✓ Step 1 完成
        r2 = await sb.execute("git add .")         # ✓ Step 2 完成
        r3 = await sb.execute('git commit -m "Initial commit"')  # ✓ Step 3 完成
        grade = sb.grade()                         # 评分结果
    """

    def __init__(self, exercise: Exercise) -> None:
        self.exercise = exercise
        self._terminal = SimulatedTerminalSandbox()
        self._current_step = 0
        self._step_results: list[bool] = []
        self._alive = False

    async def initialize(self) -> None:
        await self._terminal.initialize()
        # 执行环境初始化命令
        for cmd in self.exercise.setup_commands:
            await self._terminal.execute(cmd)
        # 清空初始化命令的历史
        self._terminal._history.clear()
        self._alive = True

    @property
    def current_step(self) -> ExerciseStep | None:
        """当前步骤。"""
        if self._current_step < len(self.exercise.steps):
            return self.exercise.steps[self._current_step]
        return None

    @property
    def current_instruction(self) -> str:
        """当前步骤的提示文字。"""
        step = self.current_step
        if step:
            return f"[步骤 {self._current_step + 1}/{len(self.exercise.steps)}] {step.instruction}"
        return "✅ 所有步骤已完成！"

    @property
    def progress(self) -> dict:
        """进度信息。"""
        return {
            "current_step": self._current_step + 1,
            "total_steps": len(self.exercise.steps),
            "completed": self._current_step >= len(self.exercise.steps),
            "correct_count": sum(self._step_results),
        }

    async def execute(self, command: str, **kwargs) -> ExecutionResult:
        """执行命令并判定当前步骤。"""
        if not self._alive:
            return ExecutionResult(error="沙箱未初始化", exit_code=-1)

        # 先在模拟终端执行
        result = await self._terminal.execute(command)

        # 判定当前步骤
        step = self.current_step
        if step:
            is_correct = self._check_command(command, step)
            # 更新历史记录的判定
            if self._terminal._history:
                self._terminal._history[-1].is_correct = is_correct

            if is_correct:
                self._step_results.append(True)
                self._current_step += 1
                self._terminal._history[-1].feedback = "✅ 正确！"

                # 如果练习定义了期望输出，用那个替换
                if step.expected_output:
                    result = ExecutionResult(
                        output=step.expected_output,
                        exit_code=0,
                        metadata={"step_completed": True},
                    )
                result.metadata["step_completed"] = True
                result.metadata["next_instruction"] = self.current_instruction
            else:
                self._terminal._history[-1].feedback = "❌ 不是当前步骤期望的命令"
                result.metadata["step_completed"] = False
                result.metadata["hint"] = step.hints[0] if step.hints else ""

        return result

    def _check_command(self, command: str, step: ExerciseStep) -> bool:
        """判定命令是否符合当前步骤要求。"""
        command = command.strip()
        for expected in step.expected_commands:
            # 精确匹配
            if command == expected:
                return True
            # 正则匹配
            try:
                if re.fullmatch(expected, command):
                    return True
            except re.error:
                pass
        return False

    def get_hints(self) -> list[str]:
        """获取当前步骤的提示。"""
        step = self.current_step
        return step.hints if step else []

    def get_history(self) -> list[CommandRecord]:
        """获取命令历史。"""
        return self._terminal.get_history()

    def grade(self) -> GradeResult:
        """评分。"""
        steps_done = sum(self._step_results)
        total_steps = len(self.exercise.steps)
        score = sum(
            self.exercise.steps[i].points
            for i in range(min(steps_done, total_steps))
            if i < len(self._step_results) and self._step_results[i]
        )

        if steps_done == total_steps:
            feedback = f"🎉 完美完成！全部 {total_steps} 步正确。"
            passed = True
        elif steps_done > 0:
            feedback = f"完成了 {steps_done}/{total_steps} 步。继续加油！"
            passed = steps_done >= total_steps * 0.6
        else:
            feedback = "还没有完成任何步骤，再试试？"
            passed = False

        return GradeResult(
            passed=passed,
            score=score,
            total=self.exercise.total_points,
            steps_completed=steps_done,
            steps_total=total_steps,
            feedback=feedback,
            command_history=self._terminal.get_history(),
        )

    async def destroy(self) -> None:
        await self._terminal.destroy()
        self._alive = False


# ═══════════════════════════════════════════════════════════════
# 内置练习题库
# ═══════════════════════════════════════════════════════════════


BUILTIN_EXERCISES: dict[str, Exercise] = {
    "git_init": Exercise(
        title="Git 基础：初始化与首次提交",
        description="学习如何初始化 Git 仓库、添加文件到暂存区、并完成第一次提交。",
        category="git",
        difficulty="入门",
        steps=[
            ExerciseStep(
                instruction="初始化一个新的 Git 仓库",
                expected_commands=["git init"],
                hints=["使用 git init 命令"],
            ),
            ExerciseStep(
                instruction="查看当前仓库状态",
                expected_commands=["git status"],
                hints=["使用 git status 查看工作区状态"],
            ),
            ExerciseStep(
                instruction="将所有文件添加到暂存区",
                expected_commands=["git add .", "git add -A", "git add --all"],
                hints=["git add 后面跟 '.' 表示添加所有文件"],
            ),
            ExerciseStep(
                instruction='提交更改，提交信息为 "Initial commit"',
                expected_commands=[
                    'git commit -m "Initial commit"',
                    "git commit -m 'Initial commit'",
                ],
                hints=["使用 git commit -m 命令，注意引号"],
            ),
            ExerciseStep(
                instruction="查看提交日志",
                expected_commands=["git log", "git log --oneline"],
                hints=["git log 或 git log --oneline"],
            ),
        ],
    ),

    "git_branch": Exercise(
        title="Git 分支：创建与切换",
        description="学习 Git 分支的创建和切换操作。",
        category="git",
        difficulty="基础",
        setup_commands=["git init", "touch README.md", "git add .", 'git commit -m "init"'],
        steps=[
            ExerciseStep(
                instruction="查看当前分支",
                expected_commands=["git branch", "git branch -a"],
                hints=["git branch 查看所有本地分支"],
            ),
            ExerciseStep(
                instruction='创建并切换到新分支 "feature"',
                expected_commands=["git checkout -b feature"],
                hints=["git checkout -b 分支名"],
            ),
            ExerciseStep(
                instruction="再次查看分支列表，确认已切换",
                expected_commands=["git branch", "git branch -a"],
            ),
        ],
    ),

    "linux_basics": Exercise(
        title="Linux 基础：文件操作",
        description="学习最常用的 Linux 文件操作命令。",
        category="linux",
        difficulty="入门",
        steps=[
            ExerciseStep(
                instruction="查看当前所在目录",
                expected_commands=["pwd"],
                hints=["pwd = Print Working Directory"],
            ),
            ExerciseStep(
                instruction="列出当前目录的所有文件（包含隐藏文件和详细信息）",
                expected_commands=["ls -la", "ls -al", "ls -l -a"],
                hints=["ls -la 可以显示隐藏文件和详细信息"],
            ),
            ExerciseStep(
                instruction='创建一个名为 "projects" 的新目录',
                expected_commands=["mkdir projects"],
                hints=["mkdir 命令用于创建目录"],
            ),
            ExerciseStep(
                instruction='在 projects 目录下创建一个名为 "hello.txt" 的文件',
                expected_commands=["touch projects/hello.txt"],
                hints=["touch 命令用于创建空文件"],
            ),
        ],
    ),

    "docker_basics": Exercise(
        title="Docker 基础：容器管理",
        description="学习 Docker 的基本容器操作命令。",
        category="docker",
        difficulty="入门",
        steps=[
            ExerciseStep(
                instruction="查看当前运行的容器",
                expected_commands=["docker ps"],
                hints=["docker ps 列出运行中的容器"],
            ),
            ExerciseStep(
                instruction="查看本地已有的镜像",
                expected_commands=["docker images"],
                hints=["docker images 列出本地镜像"],
            ),
            ExerciseStep(
                instruction="运行一个 Python 3.11 容器",
                expected_commands=[
                    "docker run python:3.11",
                    "docker run -it python:3.11",
                    "docker run --rm python:3.11",
                    "docker run -it --rm python:3.11",
                ],
                hints=["docker run 后跟镜像名:标签"],
            ),
        ],
    ),
}


def get_builtin_exercises() -> dict[str, Exercise]:
    """获取内置练习题库。"""
    return dict(BUILTIN_EXERCISES)


def get_exercise(name: str) -> Exercise | None:
    """按名称获取练习题。"""
    return BUILTIN_EXERCISES.get(name)


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════


async def create_sandbox(
    sandbox_type: SandboxType = SandboxType.TERMINAL,
    *,
    timeout: int = 30,
    custom_responses: dict[str, dict] | None = None,
) -> BaseSandbox:
    """创建沙箱。

    Args:
        sandbox_type: 沙箱类型。
        timeout: 超时（秒）。
        custom_responses: 自定义命令响应（仅模拟终端有效）。

    Returns:
        已初始化的沙箱。

    Example::

        sb = await create_sandbox(SandboxType.SIMULATED_TERMINAL)
        r = await sb.execute("git init")
        print(r.output)
        await sb.destroy()
    """
    if sandbox_type == SandboxType.TERMINAL:
        sb = LocalTerminalSandbox(sandbox_type, timeout=timeout)
    elif sandbox_type == SandboxType.CODE:
        sb = LocalCodeSandbox(sandbox_type, timeout=timeout)
    elif sandbox_type == SandboxType.SIMULATED_TERMINAL:
        sb = SimulatedTerminalSandbox(timeout=timeout, custom_responses=custom_responses or {})
    else:
        raise NotImplementedError(f"沙箱类型 `{sandbox_type}` 暂未实现")

    await sb.initialize()
    return sb


async def create_exercise_sandbox(
    exercise: Exercise | str,
) -> ExerciseSandbox:
    """创建练习模式沙箱。

    Args:
        exercise: Exercise 对象或内置练习名称。

    Returns:
        已初始化的练习沙箱。

    Example::

        sb = await create_exercise_sandbox("git_init")
        print(sb.current_instruction)           # [步骤 1/5] 初始化一个新的 Git 仓库
        r = await sb.execute("git init")         # ✓
        print(sb.current_instruction)           # [步骤 2/5] 查看当前仓库状态
        grade = sb.grade()
    """
    if isinstance(exercise, str):
        ex = get_exercise(exercise)
        if ex is None:
            available = list(BUILTIN_EXERCISES.keys())
            raise ValueError(f"练习 `{exercise}` 不存在。可用：{available}")
        exercise = ex

    sb = ExerciseSandbox(exercise)
    await sb.initialize()
    return sb
