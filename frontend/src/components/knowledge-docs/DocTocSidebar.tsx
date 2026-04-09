/* ------------------------------------------------------------------ */
/*  DocTocSidebar — Feishu-style tree TOC with collapse/expand         */
/* ------------------------------------------------------------------ */

import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, FileText } from "lucide-react";
import { cn } from "../../lib/utils";
import type { TocTreeNode } from "./types";

interface Props {
  tocTree: TocTreeNode[];
  activeHeading: string;
  collapsedTocIds: Set<string>;
  commentsForAnchor: (anchorId: string) => number;
  onTocItemClick: (id: string) => void;
  onToggleCollapse: (id: string) => void;
  tocNavRef: React.RefObject<HTMLElement | null>;
  isCollapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  activeTocText?: string;
  className?: string;
}

export function DocTocSidebar({
  tocTree,
  activeHeading,
  collapsedTocIds,
  commentsForAnchor,
  onTocItemClick,
  onToggleCollapse,
  tocNavRef,
  isCollapsed,
  onCollapsedChange,
  activeTocText,
  className,
}: Props) {
  /* Collapsed button */
  if (isCollapsed) {
    return (
      <aside className={cn("w-11 h-11", className)}>
        <button
          onClick={() => onCollapsedChange(false)}
          className="w-11 h-11 rounded-xl border border-stone-200/80 bg-stone-50/95 backdrop-blur-sm shadow-sm text-stone-600 hover:text-stone-900 hover:bg-white transition-colors flex items-center justify-center"
          aria-label="展开目录"
          title={activeTocText ? `展开目录（当前：${activeTocText}）` : "展开目录"}
        >
          <FileText className="w-4 h-4" />
          <ChevronRight className="w-3.5 h-3.5 -ml-0.5" />
        </button>
      </aside>
    );
  }

  return (
    <aside
      className={cn(
        "flex flex-col overflow-hidden",
        className,
      )}
    >
      {/* Header */}
      <div className="px-2 h-10 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 text-stone-800">
          <FileText className="w-4 h-4" />
          <span className="text-sm font-semibold">目录</span>
        </div>
        <button
          onClick={() => onCollapsedChange(true)}
          className="w-7 h-7 rounded-lg hover:bg-stone-100 transition-colors flex items-center justify-center text-stone-500 hover:text-stone-700"
          aria-label="收起目录"
        >
          <ChevronRight className="w-4 h-4 rotate-180" />
        </button>
      </div>

      {/* TOC tree */}
      <nav ref={tocNavRef as React.RefObject<HTMLElement>} className="toc-scroll flex-1 overflow-y-auto py-2 pr-1">
        {tocTree.length > 0 ? (
          <TocNodes
            nodes={tocTree}
            depth={0}
            activeHeading={activeHeading}
            collapsedTocIds={collapsedTocIds}
            commentsForAnchor={commentsForAnchor}
            onTocItemClick={onTocItemClick}
            onToggleCollapse={onToggleCollapse}
          />
        ) : (
          <div className="px-3 py-4 text-xs text-stone-400 text-center">暂无目录</div>
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
  commentsForAnchor: (anchorId: string) => number;
  onTocItemClick: (id: string) => void;
  onToggleCollapse: (id: string) => void;
}

function TocNodes({
  nodes,
  depth,
  activeHeading,
  collapsedTocIds,
  commentsForAnchor,
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
        const count = commentsForAnchor(item.id);
        const indent = depth * 16;

        return (
          <div key={item.id}>
            <div
              data-toc-id={item.id}
              className={cn(
                "group flex items-center rounded-lg transition-all duration-150 relative",
                isActive
                  ? "bg-[#F0F4FF] text-[#3370FF]"
                  : "text-[#646A73] hover:bg-[#F5F6F7] hover:text-[#1F2329]",
              )}
              style={{ paddingLeft: indent + 4 }}
            >
              {/* Left active indicator (Feishu-style) */}
              {isActive && (
                <motion.span
                  layoutId="toc-active-bar"
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-[2.5px] h-4 rounded-full bg-[#3370FF]"
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
                    "w-5 h-5 shrink-0 flex items-center justify-center rounded transition-colors",
                    isActive
                      ? "text-[#3370FF] hover:bg-[#E1EAFF]"
                      : "text-[#8F959E] hover:text-[#646A73] hover:bg-[#F5F6F7]",
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
                <span className="w-5 shrink-0" />
              )}

              {/* Title text */}
              <button
                type="button"
                onClick={() => onTocItemClick(item.id)}
                className={cn(
                  "flex-1 min-w-0 text-left py-1.5 pr-1 text-[13px] truncate transition-colors",
                  isActive ? "font-semibold" : "font-normal",
                  item.level === 1 && "font-semibold text-[13.5px]",
                )}
              >
                {item.text}
              </button>

              {/* Comment count badge */}
              {count > 0 && (
                <span className="shrink-0 w-4 h-4 mr-1 rounded-full bg-[#E1EAFF] text-[#3370FF] text-[10px] flex items-center justify-center font-medium">
                  {count}
                </span>
              )}
            </div>

            {/* Children (collapsible with animation) */}
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
                    commentsForAnchor={commentsForAnchor}
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
