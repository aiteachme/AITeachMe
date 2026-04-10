export type MinerUErrorExplanation = {
  code: string;
  title: string;
  suggestion: string;
};

const MINERU_ERROR_CODE_MAP: Record<string, Omit<MinerUErrorExplanation, "code">> = {
  A0202: {
    title: "Token 错误",
    suggestion: "检查 Token 是否正确，请检查是否有 Bearer 前缀 或者更换新 Token",
  },
  A0211: {
    title: "Token 过期",
    suggestion: "更换新 Token",
  },
  "-500": {
    title: "传参错误",
    suggestion: "请确保参数类型及 Content-Type 正确",
  },
  "-10001": {
    title: "服务异常",
    suggestion: "请稍后再试",
  },
  "-10002": {
    title: "请求参数错误",
    suggestion: "检查请求参数格式",
  },
  "-60001": {
    title: "生成上传 URL 失败，请稍后再试",
    suggestion: "请稍后再试",
  },
  "-60002": {
    title: "获取匹配的文件格式失败",
    suggestion:
      "检测文件类型失败，请求的文件名及链接中带有正确的后缀名，且文件为 pdf,doc,docx,ppt,pptx,png,jp(e)g 中的一种",
  },
  "-60003": {
    title: "文件读取失败",
    suggestion: "请检查文件是否损坏并重新上传",
  },
  "-60004": {
    title: "空文件",
    suggestion: "请上传有效文件",
  },
  "-60005": {
    title: "文件大小超出限制",
    suggestion: "检查文件大小，最大支持 200MB",
  },
  "-60006": {
    title: "文件页数超过限制",
    suggestion: "请拆分文件后重试",
  },
  "-60007": {
    title: "模型服务暂时不可用",
    suggestion: "请稍后重试或联系技术支持",
  },
  "-60008": {
    title: "文件读取超时",
    suggestion: "检查 URL 可访问",
  },
  "-60009": {
    title: "任务提交队列已满",
    suggestion: "请稍后再试",
  },
  "-60010": {
    title: "解析失败",
    suggestion: "请稍后再试",
  },
  "-60011": {
    title: "获取有效文件失败",
    suggestion: "请确保文件已上传",
  },
  "-60012": {
    title: "找不到任务",
    suggestion: "请确保 task_id 有效且未删除",
  },
  "-60013": {
    title: "没有权限访问该任务",
    suggestion: "只能访问自己提交的任务",
  },
  "-60014": {
    title: "删除运行中的任务",
    suggestion: "运行中的任务暂不支持删除",
  },
  "-60015": {
    title: "文件转换失败",
    suggestion: "可以手动转为 pdf 再上传",
  },
  "-60016": {
    title: "文件转换失败",
    suggestion: "文件转换为指定格式失败，可以尝试其他格式导出或重试",
  },
  "-60017": {
    title: "重试次数达到上限",
    suggestion: "等后续模型升级后重试",
  },
  "-60018": {
    title: "每日解析任务数量已达上限",
    suggestion: "明日再来",
  },
  "-60019": {
    title: "html 文件解析额度不足",
    suggestion: "明日再来",
  },
  "-60020": {
    title: "文件拆分失败",
    suggestion: "请稍后重试",
  },
  "-60021": {
    title: "读取文件页数失败",
    suggestion: "请稍后重试",
  },
  "-60022": {
    title: "网页读取失败",
    suggestion: "可能因网络问题或者限频导致读取失败，请稍后再试",
  },
};

function pickFirstKnownCode(message: string): string | null {
  const candidates: string[] = [];

  const alphaCodes = message.match(/\bA\d{4}\b/g);
  if (alphaCodes) candidates.push(...alphaCodes);

  const numberCodes = message.match(/-\d{3,5}\b/g);
  if (numberCodes) candidates.push(...numberCodes);

  for (const code of candidates) {
    if (code in MINERU_ERROR_CODE_MAP) return code;
  }
  return null;
}

export function explainMinerUErrorMessage(message?: string | null): MinerUErrorExplanation | null {
  if (!message) return null;

  // Some backends may embed MinerU response JSON into the message.
  // Try JSON parse as a best-effort path, but keep it conservative.
  const trimmed = message.trim();
  if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
    try {
      const decoded = JSON.parse(trimmed) as unknown;
      if (decoded && typeof decoded === "object") {
        const anyDecoded = decoded as Record<string, unknown>;
        const codeValue = anyDecoded.code;
        const code = typeof codeValue === "string" || typeof codeValue === "number" ? String(codeValue) : null;
        if (code && code in MINERU_ERROR_CODE_MAP) {
          const meta = MINERU_ERROR_CODE_MAP[code];
          return { code, ...meta };
        }
      }
    } catch {
      // ignore
    }
  }

  const code = pickFirstKnownCode(message);
  if (!code) return null;

  const meta = MINERU_ERROR_CODE_MAP[code];
  if (!meta) return null;

  return { code, ...meta };
}

export function formatMinerUErrorForUser(message?: string | null): string | null {
  const explanation = explainMinerUErrorMessage(message);
  if (!explanation) return null;
  return `${explanation.title}（${explanation.code}）。建议：${explanation.suggestion}`;
}
