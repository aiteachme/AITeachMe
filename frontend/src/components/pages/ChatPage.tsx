import {useState, useRef, useEffect} from "react";
import {Send, Plus, Image as ImageIcon, Paperclip, Trash2, Menu, X, MessageSquare} from "lucide-react";
import {Button} from "../ui/Button";
import {cn} from "../../lib/utils";

interface Message {
    id: string;
    role: "user" | "assistant";
    content: string;
    timestamp: Date;
}

interface Conversation {
    id: string;
    title: string;
    messages: Message[];
    lastUpdated: Date;
}

export function ChatPage() {
    const [conversations, setConversations] = useState<Conversation[]>([
        {
            id: "1",
            title: "高数学习助手",
            messages: [],
            lastUpdated: new Date(),
        },
    ]);

    const [currentConversationId, setCurrentConversationId] = useState<string>("1");
    const [input, setInput] = useState("");
    const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
    const [isTyping, setIsTyping] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    const currentConversation = conversations.find(c => c.id === currentConversationId);
    const messages = currentConversation?.messages || [];

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({behavior: "smooth"});
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = "auto";
            const newHeight = Math.min(textareaRef.current.scrollHeight, 200);
            textareaRef.current.style.height = newHeight + "px";
        }
    }, [input]);

    const handleSend = () => {
        if (!input.trim() || !currentConversation) return;

        const newMessage: Message = {
            id: Date.now().toString(),
            role: "user",
            content: input,
            timestamp: new Date(),
        };

        const updatedMessages = [...currentConversation.messages, newMessage];

        setConversations(conversations.map(conv =>
            conv.id === currentConversationId
                ? {
                    ...conv,
                    messages: updatedMessages,
                    title: conv.messages.length === 0 ? input.slice(0, 30) : conv.title,
                    lastUpdated: new Date()
                }
                : conv
        ));

        setInput("");
        setIsTyping(true);

        setTimeout(() => {
            const aiResponse: Message = {
                id: (Date.now() + 1).toString(),
                role: "assistant",
                content: "这是一个很好的问题！让我来帮你解答...",
                timestamp: new Date(),
            };

            setConversations(conversations.map(conv =>
                conv.id === currentConversationId
                    ? {
                        ...conv,
                        messages: [...conv.messages, newMessage, aiResponse],
                        lastUpdated: new Date()
                    }
                    : conv
            ));
            setIsTyping(false);
        }, 1000);
    };

    const createNewConversation = () => {
        const newConv: Conversation = {
            id: Date.now().toString(),
            title: "新对话",
            messages: [],
            lastUpdated: new Date(),
        };
        setConversations([newConv, ...conversations]);
        setCurrentConversationId(newConv.id);
        setIsMobileSidebarOpen(false);
    };

    const deleteConversation = (id: string) => {
        if (conversations.length === 1) return;

        const filtered = conversations.filter(c => c.id !== id);
        setConversations(filtered);

        if (currentConversationId === id) {
            setCurrentConversationId(filtered[0].id);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="flex h-[calc(100vh-4rem)] bg-gradient-to-b from-white to-slate-50/30 -m-6 lg:-m-8 relative">
            {/* Mobile Header */}
            <div className="lg:hidden absolute top-0 left-0 right-0 h-14 bg-white/80 backdrop-blur-md border-b border-slate-200/60 flex items-center px-4 z-10">
                <button
                    onClick={() => setIsMobileSidebarOpen(true)}
                    className="p-2 hover:bg-slate-100 rounded-lg transition-colors -ml-2"
                >
                    <Menu className="w-5 h-5 text-slate-700"/>
                </button>
                <div className="flex-1 text-center">
                    <h1 className="text-sm font-medium text-slate-900 truncate px-2">
                        {currentConversation?.title || "新对话"}
                    </h1>
                </div>
                <div className="w-9"/>
            </div>

            {/* Mobile Sidebar Overlay */}
            {isMobileSidebarOpen && (
                <div
                    className="lg:hidden fixed inset-0 bg-black/20 backdrop-blur-sm z-40"
                    onClick={() => setIsMobileSidebarOpen(false)}
                />
            )}

            {/* Conversation List Sidebar */}
            <div className={cn(
                "w-64 border-r border-slate-200/60 flex flex-col bg-white/50 backdrop-blur-sm transition-transform duration-300 ease-in-out",
                "lg:relative lg:translate-x-0",
                "fixed inset-y-0 left-0 z-50",
                isMobileSidebarOpen ? "translate-x-0" : "-translate-x-full"
            )}>
                {/* Mobile Close Button */}
                <div className="lg:hidden flex items-center justify-between p-4 border-b border-slate-200/60">
                    <h2 className="text-sm font-semibold text-slate-900">对话列表</h2>
                    <button
                        onClick={() => setIsMobileSidebarOpen(false)}
                        className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors"
                    >
                        <X className="w-4 h-4 text-slate-600"/>
                    </button>
                </div>

                <div className="p-3 border-b border-slate-200/60">
                    <Button
                        onClick={createNewConversation}
                        className="w-full justify-start gap-2 bg-slate-900 hover:bg-slate-800 text-white"
                    >
                        <Plus className="w-4 h-4"/>
                        新建对话
                    </Button>
                </div>

                <div className="flex-1 overflow-y-auto p-2">
                    {conversations.map((conv) => (
                        <div
                            key={conv.id}
                            className={cn(
                                "group relative mb-1 rounded-lg transition-all cursor-pointer",
                                currentConversationId === conv.id
                                    ? "bg-slate-100/80 shadow-sm"
                                    : "hover:bg-slate-50/50"
                            )}
                            onClick={() => {
                                setCurrentConversationId(conv.id);
                                setIsMobileSidebarOpen(false);
                            }}
                        >
                            <div className="p-3">
                                <div className="text-sm font-medium text-slate-900 truncate">
                                    {conv.title}
                                </div>
                                <div className="text-xs text-slate-500 mt-1">
                                    {conv.messages.length} 条消息
                                </div>
                            </div>

                            {conversations.length > 1 && (
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        deleteConversation(conv.id);
                                    }}
                                    className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-slate-200 rounded"
                                >
                                    <Trash2 className="w-3 h-3 text-slate-600"/>
                                </button>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            {/* Chat Area */}
            <div className="flex-1 flex flex-col lg:mt-0 mt-14">
                {messages.length === 0 ? (
                    /* Empty state */
                    <div className="flex-1 flex items-center justify-center px-4 pb-32">
                        <div className="w-full max-w-2xl text-center">
                            <div className="mb-12">
                                <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-slate-900 to-slate-700 mb-6 shadow-lg">
                                    <MessageSquare className="w-8 h-8 text-white"/>
                                </div>
                                <h2 className="text-2xl font-semibold text-slate-900 mb-2">
                                    {currentConversation?.title}
                                </h2>
                                <p className="text-slate-500">
                                    开始对话，我会尽力帮助你
                                </p>
                            </div>
                        </div>
                    </div>
                ) : (
                    /* Messages view */
                    <div className="flex-1 overflow-y-auto">
                        <div className="max-w-3xl mx-auto px-4 py-8">
                            {messages.map((message) => (
                                <div
                                    key={message.id}
                                    className={cn(
                                        "flex gap-4 mb-6 animate-in fade-in slide-in-from-bottom-4 duration-500",
                                        message.role === "assistant" && "bg-slate-50/50 -mx-4 px-4 py-6 rounded-2xl"
                                    )}
                                >
                                    <div
                                        className={cn(
                                            "flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-medium shadow-sm",
                                            message.role === "user"
                                                ? "bg-slate-900"
                                                : "bg-gradient-to-br from-blue-500 to-indigo-600"
                                        )}
                                    >
                                        {message.role === "user" ? "U" : "AI"}
                                    </div>
                                    <div className="flex-1 min-w-0 pt-1.5">
                                        <p className="text-[15px] leading-7 whitespace-pre-wrap text-slate-800">
                                            {message.content}
                                        </p>
                                    </div>
                                </div>
                            ))}

                            {isTyping && (
                                <div className="flex gap-4 mb-6 bg-slate-50/50 -mx-4 px-4 py-6 rounded-2xl">
                                    <div className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center bg-gradient-to-br from-blue-500 to-indigo-600 shadow-sm">
                                        <span className="text-white text-sm font-medium">AI</span>
                                    </div>
                                    <div className="flex-1 pt-1.5">
                                        <div className="flex gap-1">
                                            <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{animationDelay: "0ms"}}/>
                                            <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{animationDelay: "150ms"}}/>
                                            <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{animationDelay: "300ms"}}/>
                                        </div>
                                    </div>
                                </div>
                            )}

                            <div ref={messagesEndRef}/>
                        </div>
                    </div>
                )}

                {/* Input Area - Fixed at bottom */}
                <div className="border-t border-slate-200/60 bg-white/80 backdrop-blur-md">
                    <div className="max-w-3xl mx-auto px-4 py-4">
                        <div className="relative bg-white border border-slate-300 rounded-2xl shadow-sm hover:shadow-md focus-within:border-slate-400 focus-within:shadow-md transition-all">
                            <div className="flex items-end gap-2 p-3">
                                <div className="hidden sm:flex gap-1">
                                    <button className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded-lg transition-colors">
                                        <Paperclip className="w-5 h-5"/>
                                    </button>
                                    <button className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-50 rounded-lg transition-colors">
                                        <ImageIcon className="w-5 h-5"/>
                                    </button>
                                </div>

                                <textarea
                                    ref={textareaRef}
                                    value={input}
                                    onChange={(e) => setInput(e.target.value)}
                                    onKeyDown={handleKeyDown}
                                    placeholder="输入消息..."
                                    rows={1}
                                    className="flex-1 px-2 py-2 resize-none focus:outline-none text-[15px] text-slate-900 placeholder:text-slate-400 bg-transparent"
                                    style={{maxHeight: "200px"}}
                                />

                                <button
                                    onClick={handleSend}
                                    disabled={!input.trim()}
                                    className={cn(
                                        "p-2.5 rounded-xl transition-all flex-shrink-0",
                                        input.trim()
                                            ? "bg-slate-900 text-white hover:bg-slate-800 shadow-sm hover:shadow"
                                            : "bg-slate-100 text-slate-300 cursor-not-allowed"
                                    )}
                                >
                                    <Send className="w-5 h-5"/>
                                </button>
                            </div>
                        </div>

                        <p className="text-xs text-slate-400 text-center mt-3">
                            AI 可能会出错，请核实重要信息
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
}
