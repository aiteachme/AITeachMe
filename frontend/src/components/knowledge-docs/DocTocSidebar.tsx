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
              title={item.text}
              className={cn(
                "group flex items-center rounded-md transition-colors relative",
                isActive
                  ? "bg-blue-50 text-blue-700 font-medium"
                  : "text-[#646A73] hover:bg-[#F0F2F5] hover:text-[#1F2329]",
              )}
              style={{ paddingLeft: indent + 4 }}
            >
              {/* Left active indicator */}
              {isActive && (
                <motion.span
                  layoutId="toc-indicator"
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-3.5 rounded-full bg-blue-600"
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
                    "w-5 h-5 auto shrink-0 flex items-center justify-center rounded transition-colors mr-0.5",
                    isActive
                      ? "text-blue-700 hover:bg-blue-100"
                      : "text-[#8F959E] hover:text-[#646A73] hover:bg-[#DEE0E3]",
                  )}
                >
                  <ChevronRight
                    className={cn(
                      "w-3.5 h-3.5 transition-transform duration-200",
                      !isCollapsed && "rotate-90",
                    )}
                  />
                </button>
              ) : (
                <span className="w-5 shrink-0 mr-0.5" />
              )}

              {/* Title text */}
              <button
                type="button"
                title={item.text}
                aria-label={item.text}
                onClick={() => onTocItemClick(item.id)}
                className={cn(
                  "flex-1 min-w-0 text-left py-1 pr-2 text-[13px] truncate transition-colors",
                  item.level === 1 && "font-semibold text-[14px] text-[#1F2329]"
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
