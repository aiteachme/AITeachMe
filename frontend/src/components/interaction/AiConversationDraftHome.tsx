import { HeroAnimation } from "../ui/HeroAnimation";

interface AiConversationDraftHomeProps {
  title: string;
  description: string;
  animationKey: number;
}

export function AiConversationDraftHome({
  title,
  description,
  animationKey,
}: AiConversationDraftHomeProps) {
  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="max-w-md text-center">
        <div className="flex justify-center">
          <HeroAnimation key={animationKey} width={84} height={78} />
        </div>
        <h3 className="mt-4 text-[17px] font-semibold tracking-tight text-zinc-900 dark:text-slate-100">
          {title}
        </h3>
        <p className="mt-2 text-[13px] leading-relaxed text-zinc-500 dark:text-slate-400">
          {description}
        </p>
      </div>
    </div>
  );
}
