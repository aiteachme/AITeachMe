import { Plus } from "lucide-react";

export function ExamHeroOrb() {
  return (
    <div className="relative hidden h-[280px] w-[280px] shrink-0 items-center justify-center lg:flex">
      <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_30%_30%,rgba(34,197,94,0.95),rgba(59,130,246,0.7)_38%,rgba(168,85,247,0.92)_64%,rgba(15,23,42,0.98)_90%)]" />
      <div className="absolute inset-[16%] rounded-full border-[18px] border-white/30" />
      <div className="absolute inset-[29%] rounded-full border-[14px] border-white/45" />
      <div className="absolute inset-[42%] rounded-full border-[12px] border-white/50" />
      <div className="absolute h-3.5 w-3.5 -translate-x-[118px] -translate-y-[68px] rounded-full bg-sky-200/90" />
      <div className="absolute h-5 w-5 translate-x-[124px] -translate-y-[78px] rounded-full bg-emerald-400/90 blur-[1px]" />
      <div className="absolute h-16 w-2 rotate-45 rounded-full bg-slate-900" />
      <div className="absolute h-0 w-0 translate-x-[47px] -translate-y-[45px] border-b-[17px] border-l-[38px] border-t-[17px] border-b-transparent border-l-emerald-400 border-t-transparent" />
      <div className="absolute h-0 w-0 translate-x-[68px] -translate-y-[25px] rotate-12 border-b-[10px] border-l-[20px] border-t-[10px] border-b-transparent border-l-emerald-300 border-t-transparent" />
      <div className="absolute right-0 top-[60%] grid h-10 w-10 place-items-center rounded-full bg-white/75 backdrop-blur">
        <Plus className="h-5 w-5 text-sky-500" />
      </div>
    </div>
  );
}
