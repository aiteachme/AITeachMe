import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bot, GraduationCap, Sparkles, FileText, Database, Network } from "lucide-react";

export function HeroAnimation() {
  const [scene, setScene] = useState<"learning" | "transforming" | "teaching">("learning");

  useEffect(() => {
    let timers: ReturnType<typeof setTimeout>[] = [];
    
    const runCycle = () => {
      setScene("learning");
      timers.push(setTimeout(() => setScene("transforming"), 4000));
      timers.push(setTimeout(() => setScene("teaching"), 4600));
      timers.push(setTimeout(() => runCycle(), 9500));
    };

    timers.push(setTimeout(() => setScene("transforming"), 4000));
    timers.push(setTimeout(() => setScene("teaching"), 4600));
    timers.push(setTimeout(() => runCycle(), 9500));

    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="relative w-[110px] h-[110px] flex items-center justify-center shrink-0">
      {/* Dynamic Background Glow */}
      <motion.div 
        animate={{ 
          scale: scene === "transforming" ? 1.5 : scene === "teaching" ? 1.2 : 1,
          opacity: scene === "transforming" ? 0.9 : scene === "teaching" ? 0.4 : 0.2,
          backgroundColor: scene === "teaching" ? "#3b82f6" : "#6366f1",
          borderRadius: scene === "transforming" ? "30%" : "50%"
        }}
        transition={{ duration: 0.6, ease: "easeInOut" }}
        className="absolute inset-0 blur-xl pointer-events-none"
      />
      
      <AnimatePresence mode="wait">
        {scene === "learning" && (
          <motion.div
            key="learning"
            initial={{ opacity: 0, scale: 0.8, filter: "blur(4px)" }}
            animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 0.5, rotateY: -180, filter: "blur(8px)" }}
            transition={{ duration: 0.5, type: "spring", stiffness: 200 }}
            className="flex items-center justify-center relative z-10 w-full h-full perspective-1000"
          >
            {/* The Learning Robot Center */}
            <motion.div
              animate={{ y: [0, -3, 0] }}
              transition={{ repeat: Infinity, duration: 2, ease: "easeInOut" }}
              className="bg-gradient-to-br from-indigo-600 to-slate-900 border border-indigo-400/30 text-white p-3.5 rounded-[1.2rem] shadow-[0_8px_30px_rgb(79,70,229,0.3)] relative z-20 flex items-center justify-center"
            >
              <Bot className="w-8 h-8" />
              {/* Internal scanning laser blip */}
              <motion.div 
                animate={{ opacity: [0, 0.8, 0], scaleY: [0.1, 1, 0.1] }}
                transition={{ repeat: Infinity, duration: 1.5 }}
                className="absolute inset-x-3 top-1/2 h-0.5 bg-indigo-300/60 shadow-[0_0_8px_rgb(165,180,252)] pointer-events-none mix-blend-screen"
              />
            </motion.div>
            
            {/* Knowledge being absorbed (Documents, Databases, Graphs) */}
            <motion.div
              animate={{ x: [35, 0], y: [-30, 0], scale: [1, 0], opacity: [0, 1, 0], rotate: [-20, 10] }}
              transition={{ repeat: Infinity, duration: 1.4, ease: "easeIn", delay: 0 }}
              className="absolute z-10 text-blue-500 bg-white p-1.5 rounded-lg shadow-sm border border-blue-100"
              style={{ left: "55%", top: "-10%" }}
            >
              <FileText className="w-12 h-12" />
            </motion.div>

            <motion.div
              animate={{ x: [-35, 0], y: [20, 0], scale: [1, 0], opacity: [0, 1, 0], rotate: [20, -10] }}
              transition={{ repeat: Infinity, duration: 1.7, ease: "easeIn", delay: 0.5 }}
              className="absolute z-10 text-indigo-500 bg-white p-1.5 rounded-lg shadow-sm border border-indigo-100"
              style={{ right: "55%", bottom: "-5%" }}
            >
              <Database className="w-12 h-12" />
            </motion.div>

            <motion.div
              animate={{ x: [25, 0], y: [25, 0], scale: [1, 0], opacity: [0, 1, 0], rotate: [15, -5] }}
              transition={{ repeat: Infinity, duration: 1.5, ease: "easeIn", delay: 1.1 }}
              className="absolute z-10 text-emerald-500 bg-white p-1.5 rounded-lg shadow-sm border border-emerald-100"
              style={{ left: "55%", bottom: "-5%" }}
            >
              <Network className="w-12 h-12" />
            </motion.div>
          </motion.div>
        )}

        {scene === "teaching" && (
          <motion.div
            key="teaching"
            initial={{ opacity: 0, scale: 0.5, rotateY: 180, filter: "blur(8px)" }}
            animate={{ opacity: 1, scale: 1, rotateY: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 0.8 }}
            transition={{ type: "spring", stiffness: 200, damping: 20 }}
            className="flex relative z-10 w-full h-full items-center justify-center perspective-1000"
          >
            {/* Teacher / AI Companion */}
            <motion.div
              animate={{ y: [0, -6, 0] }}
              transition={{ repeat: Infinity, duration: 3, ease: "easeInOut" }}
              className="bg-gradient-to-tr from-blue-600 to-indigo-500 text-white p-4 rounded-[1.3rem] shadow-[0_12px_40px_rgb(59,130,246,0.4)] border border-blue-300/40 relative z-20"
            >
              <div className="relative">
                <Bot className="w-9 h-9" />
                {/* Floating Graduation Cap */}
                <motion.div
                  animate={{ y: [0, -3, 0], rotate: [12, 16, 12] }}
                  transition={{ repeat: Infinity, duration: 2.5, ease: "easeInOut" }}
                  className="absolute -top-[1.1rem] -right-3 drop-shadow-md"
                >
                  <GraduationCap className="w-7 h-7 text-amber-300" />
                </motion.div>
              </div>
              
              {/* Teaching aura expanding outward */}
              <motion.div
                animate={{ scale: [1, 1.6], opacity: [0.6, 0] }}
                transition={{ repeat: Infinity, duration: 2, ease: "easeOut" }}
                className="absolute inset-0 border-[3px] border-blue-300 rounded-[1.3rem] pointer-events-none"
              />
              <motion.div
                animate={{ scale: [1, 1.9], opacity: [0.3, 0] }}
                transition={{ repeat: Infinity, duration: 2, delay: 0.5, ease: "easeOut" }}
                className="absolute inset-0 border-[2px] border-blue-200 rounded-[1.3rem] pointer-events-none"
              />
            </motion.div>
            
            {/* Teaching Output Sparkles: "Enlightenment" */}
            <motion.div
              animate={{ opacity: [0, 1, 0], y: [0, -18], x: [0, 22], scale: [0.5, 1.2, 0.8] }}
              transition={{ repeat: Infinity, duration: 2 }}
              className="absolute top-0 right-0 z-30 drop-shadow-md text-amber-300"
            >
              <Sparkles className="w-5 h-5 fill-amber-300" />
            </motion.div>
            
            <motion.div
              animate={{ opacity: [0, 1, 0], y: [0, 18], x: [0, -18], scale: [0.5, 1, 0.5] }}
              transition={{ repeat: Infinity, duration: 2.5, delay: 0.8 }}
              className="absolute bottom-0 left-0 z-30 drop-shadow-sm text-blue-200"
            >
              <Sparkles className="w-4 h-4 fill-blue-200" />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
