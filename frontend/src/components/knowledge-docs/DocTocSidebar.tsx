import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { cn } from "../../lib/utils";
import type { TocTreeNode } from "./types";
import { useState } from "react";

interface Props {
  tocTree: TocTreeNode[];
  activeHeading: string;
  onTocItemClick: (id: string) => void;
  className?: string;
}

export function DocTocSidebar({
  tocTree,
  activeHeading,
  onTocItemClick,
  className,
}: Props) {
  const [collapsedTocIds, setCollapsedTocIds] = useState<Set<string>>(new Set());

  const onToggleCollapse = (id: string) => {
    setCollapsedTocIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <aside className={cn("flex flex-col py-2 px-3", className)}>
      <nav className="toc-scroll flex-1 overflow-y-auto">
        {tocTree && tocTree.length > 0 ? (
          <TocNodes
            nodes={tocTree}
            depth={0}
            activeHeading={activeHeading}
            collapsedTocIds={collapsedTocIds}
            onTocItemClick={onTocItemClick}
            onToggleCollapse={onToggleCollapse}
          />
        ) : (
          <div className="px-3 py-4 text-xs text-slate-400 text-center">暂无目录</div>
        )}
      </nav>
    </aside>
  );
}

/* ---- Recursive TOC Node Renderer ---- */

interface TocNodesProps {
  nodes: TocTreeNode[];
  depth: number;
  activeHeading: string;
  collapsedTocIds: Set<string>;
  onTocItemClick: (id: string) => void;
  onToggleCollapse: (id: string) => void;
}

function TocNodes({
  nodes,
  depth,
  activeHeading,
  collapsedTocIds,
  onTocItemClick,
  onToggleCollapse,
}: TocNodesProps) {
  return (
    <>
      {nodes.map((node) => {
        const { item } = node;
        const hasChildren = node.children.length > 0;
        const isCollapsed = collapsedTocIds.has(item.id);
        const isActive = activeHeading === item.id;
        const indent = depth * 12;

        return (
          <div key={item.id} className="my-0.5">
            <div
              data-toc-id={item.id}
              className={cn(
                "group flex items-center rounded-md transition-all duration-150 relative",
                isActive
                  ? "bg-slate-100 text-slate-900 font-semibold"
                  : "text-slate-500 hover:bg-slate-50 hover:text-slate-800",
              )}
              style={{ paddingLeft: indent + 4 }}
            >
              {/* Left active indicator */}
              {isActive && (
                <motion.span
                  layoutId="toc-indicator"
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-3.5 rounded-full bg-slate-800"
                  transition={{ type: "spring", stiffness: 380, damping: 30 }}
                />
              )}

              {/* Expand/collapse arrow */}
              {hasChildren ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleCollapse(item.id);
                  }}
                  className={cn(
                    "w-5 h-5 shrink-0 flex items-center justify-center rounded-md transition-colors",
                    isActive
                      ? "text-slate-600 hover:bg-slate-200"
                      : "text-slate-400 hover:text-slate-600 hover:bg-slate-100",
                  )}
                >
                  <ChevronRight
                    className={cn(
                      "w-3 h-3 transition-transform duration-200",
                      !isCollapsed && "rotate-90",
                    )}
                  />
                </button>
              ) : (
                <span className="w-5 shrink-0" />
              )}

              {/* Title text */}
              <button
                type="button"
                onClick={() => onTocItemClick(item.id)}
                className={cn(
                  "flex-1 min-w-0 text-left py-1.5 pr-2 text-sm truncate transition-colors",
                  item.level === 1 && "font-medium text-[14px]",
                )}
              >
                {item.text}
              </button>
            </div>

            {/* Children */}
            <AnimatePresence initial={false}>
              {hasChildren && !isCollapsed && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: "easeInOut" }}
                  className="overflow-hidden"
                >
                  <TocNodes
                    nodes={node.children}
                    depth={depth + 1}
                    activeHeading={activeHeading}
                    collapsedTocIds={collapsedTocIds}
                    onTocItemClick={onTocItemClick}
                    onToggleCollapse={onToggleCollapse}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </>
  );
}
