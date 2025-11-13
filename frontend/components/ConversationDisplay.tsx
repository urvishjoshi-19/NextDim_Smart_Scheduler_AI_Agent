"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { User, Bot } from "lucide-react";

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
}

interface ConversationDisplayProps {
  messages: Message[];
}

export default function ConversationDisplay({ messages }: ConversationDisplayProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const validMessages = messages.filter((msg) => msg.content.trim().length > 0);

  if (validMessages.length === 0) {
    return null;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
      className="w-full max-w-3xl mt-12"
    >
      <div
        ref={scrollRef}
        className="max-h-96 overflow-y-auto space-y-4 px-4 py-6 glass rounded-3xl"
      >
        <AnimatePresence mode="popLayout">
          {validMessages.map((message, index) => (
            <motion.div
              key={`${message.timestamp}-${index}`}
              initial={{ opacity: 0, y: 10, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{
                type: "spring",
                stiffness: 300,
                damping: 30,
              }}
              className={`
                flex gap-3
                ${message.role === "user" ? "justify-end" : "justify-start"}
              `}
            >
              {message.role !== "user" && (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: "spring", delay: 0.1 }}
                  className={`
                    flex-shrink-0 w-10 h-10 rounded-full
                    flex items-center justify-center
                    ${
                      message.role === "assistant"
                        ? "bg-gradient-purple"
                        : "bg-glass-white"
                    }
                  `}
                >
                  {message.role === "assistant" ? (
                    <Bot className="w-5 h-5 text-white" />
                  ) : (
                    <div className="w-2 h-2 rounded-full bg-purple-light" />
                  )}
                </motion.div>
              )}

              <motion.div
                className={`
                  max-w-md px-5 py-3 rounded-2xl
                  ${
                    message.role === "user"
                      ? "bg-gradient-purple text-white rounded-br-sm"
                      : message.role === "assistant"
                      ? "glass-strong text-white rounded-bl-sm"
                      : "glass text-gray-300 text-sm italic"
                  }
                `}
                whileHover={{ scale: 1.02 }}
                transition={{ type: "spring", stiffness: 400 }}
              >
                <p className="leading-relaxed">{message.content}</p>
              </motion.div>

              {message.role === "user" && (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: "spring", delay: 0.1 }}
                  className="flex-shrink-0 w-10 h-10 rounded-full bg-white/10 flex items-center justify-center"
                >
                  <User className="w-5 h-5 text-purple-light" />
                </motion.div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

