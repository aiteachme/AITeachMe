import Link from "next/link";
import type { ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  BrainCircuit,
  CircleCheck,
  ExternalLink,
  GraduationCap,
  Info,
  Library,
  MessageSquareText,
  Network,
  Settings2,
  Share2,
  Target,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

type TaskIcon =
  | "course"
  | "library"
  | "read"
  | "graph"
  | "chat"
  | "practice"
  | "profile"
  | "share"
  | "settings";

type EngineTrack = "ingest" | "digest" | "interact" | "examine" | "profile";
type TaskAccent = "primary" | "blue";

const taskIcons: Record<TaskIcon, LucideIcon> = {
  course: GraduationCap,
  library: Library,
  read: BookOpen,
  graph: Network,
  chat: MessageSquareText,
  practice: Target,
  profile: BrainCircuit,
  share: Share2,
  settings: Settings2,
};

const calloutIcons = {
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
} satisfies Record<"info" | "success" | "warning", LucideIcon>;

export function DocsHomeHero() {
  return (
    <section className="atm-docs-hero">
      <p className="atm-docs-eyebrow">五引擎学习闭环</p>
      <h1>
        把自己的资料，
        <br />
        <span className="atm-docs-hero-nowrap">学成真正会用的知识</span>
      </h1>
      <p className="atm-docs-hero-description">
        从上传资料到知识文档、训练讲评和课程画像，沿着真实学习路径完成一门课。
      </p>
      <div className="atm-docs-hero-actions">
        <Link
          className="atm-docs-button atm-docs-button-primary"
          href="/docs/quickstart/first-course"
        >
          5 分钟开始
          <ArrowRight aria-hidden="true" />
        </Link>
        <a
          className="atm-docs-button atm-docs-button-secondary"
          href="https://aiteachme.cn/"
          target="_blank"
          rel="noreferrer"
          aria-label="打开 AITeachMe（在新标签页打开）"
        >
          打开 AITeachMe
          <ExternalLink aria-hidden="true" />
        </a>
      </div>
    </section>
  );
}

const productEvidenceItems = [
  {
    number: "01",
    engine: "织网",
    track: "digest",
    title: "先校对，再构建",
    description: "在方案页确认范围、顺序和资料，避免一开始就生成一门方向错误的课程。",
    href: "/docs/user-guide/build-course",
    src: "/screenshots/build-plan-current.png",
    alt: "AITeachMe 课程方案页，展示课程结构、所用资料和开始构建入口",
  },
  {
    number: "02",
    engine: "伴读",
    track: "interact",
    title: "读到哪里，就从哪里追问",
    description: "知识文档与 AI 交互并排保留，让解释始终带着当前课程和章节上下文。",
    href: "/docs/user-guide/chat",
    src: "/screenshots/course-chat-current.png",
    alt: "AITeachMe 知识文档与 AI 交互窗口并排显示",
  },
  {
    number: "03",
    engine: "诊断",
    track: "examine",
    title: "用训练核对理解",
    description: "测验、考卷和闯关服务于不同阶段，先复核题目与题解，再看分数。",
    href: "/docs/user-guide/exam-modes",
    src: "/screenshots/exams-training-center.png",
    alt: "AITeachMe 训练中心，展示测验、考卷和闯关入口",
  },
  {
    number: "04",
    engine: "显影",
    track: "profile",
    title: "让画像把你带回薄弱点",
    description: "掌握度来自真实作答记录，用它决定下一章、下一轮训练和复习重点。",
    href: "/docs/user-guide/review-profile",
    src: "/screenshots/profile-course-current.png",
    alt: "AITeachMe 课程画像，展示掌握度、薄弱点和学习记录",
  },
] as const;

export function ProductEvidence() {
  return (
    <div className="atm-docs-evidence-grid">
      {productEvidenceItems.map((item) => (
        <article
          className={`atm-docs-evidence-item atm-docs-track-${item.track}`}
          key={item.number}
        >
          <div className="atm-docs-evidence-meta">
            <span>{item.number}</span>
            <span>{item.engine}</span>
          </div>
          <h3>
            <Link href={item.href}>
              {item.title}
              <ArrowRight aria-hidden="true" />
            </Link>
          </h3>
          <p>{item.description}</p>
          <Link className="atm-docs-evidence-image" href={item.href}>
            <img
              src={item.src}
              alt={item.alt}
              loading="lazy"
              decoding="async"
              width={1440}
              height={900}
            />
          </Link>
        </article>
      ))}
    </div>
  );
}

export function TaskGrid({ children }: { children: ReactNode }) {
  return <div className="atm-docs-task-grid">{children}</div>;
}

export function TaskCard({
  title,
  description,
  href,
  icon,
  accent,
  label,
}: {
  title: string;
  description: string;
  href: string;
  icon: TaskIcon;
  accent: TaskAccent;
  label?: string;
}) {
  const Icon = taskIcons[icon];

  return (
    <Link className={`atm-docs-task-card atm-docs-accent-${accent}`} href={href}>
      <span className="atm-docs-task-icon" aria-hidden="true">
        <Icon />
      </span>
      <span className="atm-docs-task-copy">
        {label ? <span className="atm-docs-task-label">{label}</span> : null}
        <strong>{title}</strong>
        <span>{description}</span>
      </span>
      <ArrowRight className="atm-docs-task-arrow" aria-hidden="true" />
    </Link>
  );
}

const loopItems = [
  ["01", "透视 · 准备资料", "上传资料，确认内容可用", "ingest"],
  ["02", "织网 · 构建课程", "校对方案，生成知识脉络", "digest"],
  ["03", "伴读 · 阅读追问", "结合文档、图谱和问答学习", "interact"],
  ["04", "诊断 · 训练讲评", "用测验和考卷检验理解", "examine"],
  ["05", "显影 · 复盘画像", "复核题解，回到薄弱点", "profile"],
] as const;

export function LearningLoop() {
  return (
    <ol className="atm-docs-loop" aria-label="AITeachMe 学习轨迹">
      {loopItems.map(([number, title, description, track]) => (
        <li className={`atm-docs-track-${track}`} key={number}>
          <span aria-hidden="true">{number}</span>
          <div>
            <strong>{title}</strong>
            <p>{description}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function ProductShot({
  src,
  alt,
  caption,
  eager = false,
}: {
  src: string;
  alt: string;
  caption: ReactNode;
  eager?: boolean;
}) {
  return (
    <figure className="atm-docs-product-shot">
      <div className="atm-docs-product-shot-frame">
        <a
          href={src}
          target="_blank"
          rel="noreferrer"
          aria-label={`${alt}，在新标签页打开原图`}
        >
          <img src={src} alt={alt} loading={eager ? "eager" : "lazy"} width={1440} height={900} />
        </a>
      </div>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

export function GuideCallout({
  title,
  children,
  tone = "info",
}: {
  title: string;
  children: ReactNode;
  tone?: "info" | "success" | "warning";
}) {
  const Icon = calloutIcons[tone];

  return (
    <div
      className={`atm-docs-callout atm-docs-callout-${tone}`}
      role="note"
      aria-label={title}
    >
      <Icon className="atm-docs-callout-icon" aria-hidden="true" />
      <div className="atm-docs-callout-content">
        <strong>{title}</strong>
        <div>{children}</div>
      </div>
    </div>
  );
}

export function PromptExample({ children }: { children: ReactNode }) {
  return <div className="atm-docs-prompt-example">{children}</div>;
}

export function GuideSteps({ children }: { children: ReactNode }) {
  return <ol className="atm-docs-steps">{children}</ol>;
}

export function GuideStep({
  number,
  title,
  children,
}: {
  number: number;
  title: string;
  children: ReactNode;
}) {
  return (
    <li>
      <span className="atm-docs-step-number" aria-hidden="true">
        {String(number).padStart(2, "0")}
      </span>
      <div className="atm-docs-step-content">
        <h3>{title}</h3>
        {children}
      </div>
    </li>
  );
}

export function GuideFooter({
  previous,
  previousHref,
  next,
  nextHref,
}: {
  previous?: string;
  previousHref?: string;
  next: string;
  nextHref: string;
}) {
  return (
    <nav className="atm-docs-guide-footer" aria-label="教程翻页">
      {previous && previousHref ? (
        <Link href={previousHref}>
          <span className="atm-docs-guide-footer-direction">
            <ArrowLeft aria-hidden="true" />
            上一步
          </span>
          <strong>{previous}</strong>
        </Link>
      ) : (
        <span />
      )}
      <Link href={nextHref} className="atm-docs-guide-footer-next">
        <span className="atm-docs-guide-footer-direction">
          下一步
          <ArrowRight aria-hidden="true" />
        </span>
        <strong>{next}</strong>
      </Link>
    </nav>
  );
}
