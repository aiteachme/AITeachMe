import type { ChatModelChoice } from "../../chat/ChatModelSelect";
import type { FileRecord } from "../../../types/files";
import type { PendingSelectionContext } from "./AiConversationTypes";
import { AiConversationComposerDock } from "./AiConversationComposerDock";
import { AiConversationDraftFileAttachments } from "./AiConversationDraftFileAttachments";

interface AiConversationDraftPageProps {
  title: string;
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
  attachedFileIds?: string[];
  attachedFiles?: FileRecord[];
  onAttachedFilesChange?: (fileIds: string[], files: FileRecord[]) => void;
  onUploadingChange?: (isUploading: boolean) => void;
  enableAttachments?: boolean;
}

export function AiConversationDraftPage({
  title,
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
  attachedFileIds = [],
  attachedFiles = [],
  onAttachedFilesChange,
  onUploadingChange,
  enableAttachments = false,
}: AiConversationDraftPageProps) {
  const composer = (
    <AiConversationComposerDock
      draft={draft}
      onDraftChange={onDraftChange}
      onSend={onSend}
      onAbort={onAbort}
      isStreaming={isStreaming}
      disabled={disabled}
      autoFocusKey={autoFocusKey}
      modelValue={modelValue}
      onModelChange={onModelChange}
      isPlannerConversation={isPlannerConversation}
      pendingSelectionContext={pendingSelectionContext}
      onClearPendingSelectionContext={onClearPendingSelectionContext}
      layout="home"
      canSend={draft.trim().length > 0}
    />
  );

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto bg-[#fafafa] px-4 py-8 dark:bg-[#0b0f19]">
      <div className="relative z-20 mx-auto my-auto flex w-full max-w-[720px] flex-col items-center">
        <h1 className="mb-9 text-center text-[28px] font-semibold tracking-normal text-zinc-900 dark:text-slate-100">
          {title}
        </h1>

        {enableAttachments && onAttachedFilesChange && onUploadingChange ? (
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
        ) : composer}
      </div>
    </div>
  );
}
