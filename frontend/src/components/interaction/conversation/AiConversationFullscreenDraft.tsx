import type { ChatModelChoice } from "../../chat/ChatModelSelect";
import { HeroAnimation } from "../../ui/HeroAnimation";
import type { FileRecord } from "../../../types/files";
import type { PendingSelectionContext } from "./AiConversationTypes";
import { AiConversationComposerDock } from "./AiConversationComposerDock";
import { AiConversationDraftFileAttachments } from "./AiConversationDraftFileAttachments";

interface AiConversationFullscreenDraftProps {
  animationKey: number;
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  onAbort: () => void;
  isStreaming: boolean;
  disabled: boolean;
  autoFocusKey: number;
  modelValue: ChatModelChoice;
  onModelChange: (value: ChatModelChoice) => void;
  isPlannerConversation: boolean;
  pendingSelectionContext: PendingSelectionContext | null;
  onClearPendingSelectionContext: () => void;
  attachedFileIds: string[];
  attachedFiles: FileRecord[];
  onAttachedFilesChange: (fileIds: string[], files: FileRecord[]) => void;
  onUploadingChange: (isUploading: boolean) => void;
}

export function AiConversationFullscreenDraft({
  animationKey,
  draft,
  onDraftChange,
  onSend,
  onAbort,
  isStreaming,
  disabled,
  autoFocusKey,
  modelValue,
  onModelChange,
  isPlannerConversation,
  pendingSelectionContext,
  onClearPendingSelectionContext,
  attachedFileIds,
  attachedFiles,
  onAttachedFilesChange,
  onUploadingChange,
}: AiConversationFullscreenDraftProps) {
  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto bg-[#fafafa] px-4 py-8 dark:bg-[#0b0f19]">
      <div className="relative z-20 mx-auto my-auto flex w-full max-w-[800px] flex-col items-center">
        <div className="mb-2 flex flex-col items-center justify-center">
          <HeroAnimation key={animationKey} />
          <div className="mt-3 flex flex-col items-center">
            <h1
              className="animate-text-gradient bg-gradient-to-r from-slate-800 via-indigo-700 to-violet-600 bg-[length:200%_auto] bg-clip-text text-2xl font-bold tracking-tight text-transparent dark:from-slate-100 dark:via-indigo-400 dark:to-violet-400 md:text-3xl"
            >
              AITeachMe
            </h1>
          </div>
        </div>

        <p className="mb-8 px-4 text-center text-base leading-relaxed text-zinc-500 dark:text-slate-400">
          把任何令人头疼的学习资料，变成你的 24 小时专属“赛博私教”。
        </p>

        <AiConversationDraftFileAttachments
          fileIds={attachedFileIds}
          files={attachedFiles}
          onChange={onAttachedFilesChange}
          onUploadingChange={onUploadingChange}
          disabled={disabled || isStreaming}
        >
          {({
            attachmentContent,
            toolbarActions,
            modalContent,
            hasFiles,
            isUploading,
            onPaste,
          }) => (
            <>
              <AiConversationComposerDock
                draft={draft}
                onDraftChange={onDraftChange}
                onSend={onSend}
                onAbort={onAbort}
                isStreaming={isStreaming}
                disabled={disabled || isUploading}
                autoFocusKey={autoFocusKey}
                modelValue={modelValue}
                onModelChange={onModelChange}
                isPlannerConversation={isPlannerConversation}
                pendingSelectionContext={pendingSelectionContext}
                onClearPendingSelectionContext={onClearPendingSelectionContext}
                layout="home"
                canSend={draft.trim().length > 0 || hasFiles}
                homeAttachmentContent={attachmentContent}
                homeToolbarActions={toolbarActions}
                homeHighlighted={hasFiles}
                onPaste={onPaste}
              />
              {modalContent}
            </>
          )}
        </AiConversationDraftFileAttachments>
      </div>
    </div>
  );
}
