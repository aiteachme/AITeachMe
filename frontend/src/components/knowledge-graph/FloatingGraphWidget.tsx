import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Map } from "lucide-react";

import { KnowledgeGraphSidePanel } from "./KnowledgeGraphSidePanel";

export function FloatingGraphWidget({ courseId }: { courseId: string }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <AnimatePresence>
        {!isOpen ? (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.14 }}
            className="fixed bottom-6 right-8 z-[60]"
          >
            <button
              type="button"
              onClick={() => setIsOpen(true)}
              className="group flex h-14 items-center gap-3 overflow-hidden rounded-full border border-blue-200 bg-white/96 pl-4 pr-2.5 shadow-[0_8px_24px_rgba(0,0,0,0.12)] transition-colors hover:border-blue-300 hover:bg-white"
            >
              <div className="flex flex-col items-start pr-2">
                <span className="text-sm font-semibold text-slate-800">????</span>
                <span className="text-[10px] font-medium text-slate-500">?????????</span>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-50 text-blue-600 transition-colors group-hover:bg-blue-100 group-hover:text-blue-700">
                <Map className="h-5 w-5" />
              </div>
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {isOpen ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="fixed inset-0 z-[70] bg-slate-900/24"
            onClick={(event) => {
              if (event.target === event.currentTarget) {
                setIsOpen(false);
              }
            }}
          >
            <motion.div
              initial={{ y: "100%", opacity: 0.8 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: "100%", opacity: 0 }}
              transition={{ duration: 0.18, ease: "easeOut" }}
              className="absolute bottom-0 right-0 h-[88vh] w-full overflow-hidden rounded-t-3xl border border-slate-200 bg-white shadow-2xl sm:bottom-6 sm:right-6 sm:h-[760px] sm:w-[980px] sm:rounded-2xl"
            >
              <div className="flex items-center justify-end border-b border-slate-100 px-4 py-3">
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="rounded-md bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-200 hover:text-slate-900"
                >
                  ??
                </button>
              </div>
              <div className="h-[calc(100%-52px)]">
                <KnowledgeGraphSidePanel courseId={courseId} />
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </>
  );
}
