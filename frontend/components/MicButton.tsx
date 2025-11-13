"use client";

import { motion } from "framer-motion";
import { Mic, MicOff, Loader2 } from "lucide-react";

interface MicButtonProps {
  isRecording: boolean;
  voiceState: "idle" | "listening" | "thinking" | "speaking";
  connectionStatus: "connecting" | "connected" | "disconnected" | "error";
  onToggle: () => void;
}

export default function MicButton({
  isRecording,
  voiceState,
  connectionStatus,
  onToggle,
}: MicButtonProps) {
  const isDisabled = 
    connectionStatus !== "connected" || 
    voiceState === "speaking" || 
    voiceState === "thinking";

  return (
    <div className="relative flex items-center justify-center">
      {voiceState === "listening" && (
        <>
          <motion.div
            className="absolute w-48 h-48 rounded-full border-2 border-purple-primary/30"
            initial={{ scale: 1, opacity: 0.8 }}
            animate={{ scale: 1.5, opacity: 0 }}
            transition={{
              duration: 2,
              repeat: Infinity,
              ease: "easeOut",
            }}
          />
          <motion.div
            className="absolute w-48 h-48 rounded-full border-2 border-purple-primary/30"
            initial={{ scale: 1, opacity: 0.8 }}
            animate={{ scale: 1.5, opacity: 0 }}
            transition={{
              duration: 2,
              repeat: Infinity,
              ease: "easeOut",
              delay: 0.5,
            }}
          />
          <motion.div
            className="absolute w-48 h-48 rounded-full border-2 border-purple-primary/30"
            initial={{ scale: 1, opacity: 0.8 }}
            animate={{ scale: 1.5, opacity: 0 }}
            transition={{
              duration: 2,
              repeat: Infinity,
              ease: "easeOut",
              delay: 1,
            }}
          />
        </>
      )}

      {(isRecording || voiceState === "thinking" || voiceState === "speaking") && (
        <motion.div
          className="absolute w-40 h-40 rounded-full bg-purple-primary/20 blur-2xl"
          animate={{
            scale: [1, 1.2, 1],
            opacity: [0.5, 0.8, 0.5],
          }}
          transition={{
            duration: 2,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        />
      )}

      <motion.button
        onClick={onToggle}
        disabled={isDisabled}
        className={`
          relative z-10 w-32 h-32 rounded-full
          flex items-center justify-center
          glass-strong
          transition-all duration-300
          ${!isDisabled ? "cursor-pointer" : "cursor-not-allowed opacity-50"}
          ${isRecording ? "shadow-glow-purple-lg" : "shadow-glass hover:shadow-glow-purple"}
        `}
        whileHover={!isDisabled ? { scale: 1.05 } : {}}
        whileTap={!isDisabled ? { scale: 0.95 } : {}}
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 20 }}
      >
        <motion.div
          className={`
            absolute inset-2 rounded-full
            ${isRecording ? "bg-gradient-purple" : "bg-glass-white"}
          `}
          animate={
            voiceState === "thinking"
              ? {
                  rotate: 360,
                }
              : {}
          }
          transition={
            voiceState === "thinking"
              ? {
                  duration: 2,
                  repeat: Infinity,
                  ease: "linear",
                }
              : {}
          }
        />

        <div className="relative z-10">
          {connectionStatus === "connecting" && (
            <Loader2 className="w-12 h-12 text-purple-light animate-spin" />
          )}
          
          {connectionStatus === "connected" && voiceState === "idle" && !isRecording && (
            <motion.div
              animate={{ scale: [1, 1.1, 1] }}
              transition={{ duration: 2, repeat: Infinity }}
            >
              <Mic className="w-12 h-12 text-white" />
            </motion.div>
          )}
          
          {connectionStatus === "connected" && isRecording && voiceState === "listening" && (
            <motion.div
              animate={{
                scale: [1, 1.2, 1],
              }}
              transition={{
                duration: 1,
                repeat: Infinity,
                ease: "easeInOut",
              }}
            >
              <Mic className="w-12 h-12 text-white" />
            </motion.div>
          )}
          
          {voiceState === "thinking" && (
            <div className="wave-container">
              <div className="wave"></div>
              <div className="wave"></div>
              <div className="wave"></div>
              <div className="wave"></div>
              <div className="wave"></div>
              <div className="wave"></div>
              <div className="wave"></div>
              <div className="wave"></div>
              <div className="wave"></div>
              <div className="wave"></div>
            </div>
          )}
          
          {voiceState === "speaking" && (
            <motion.div
              animate={{
                scale: [1, 1.05, 1],
              }}
              transition={{
                duration: 0.5,
                repeat: Infinity,
                ease: "easeInOut",
              }}
            >
              <div className="flex items-center gap-1">
                <motion.div
                  className="w-2 h-8 bg-white rounded-full"
                  animate={{ height: [32, 16, 32] }}
                  transition={{ duration: 0.5, repeat: Infinity, delay: 0 }}
                />
                <motion.div
                  className="w-2 h-8 bg-white rounded-full"
                  animate={{ height: [32, 20, 32] }}
                  transition={{ duration: 0.5, repeat: Infinity, delay: 0.1 }}
                />
                <motion.div
                  className="w-2 h-8 bg-white rounded-full"
                  animate={{ height: [32, 24, 32] }}
                  transition={{ duration: 0.5, repeat: Infinity, delay: 0.2 }}
                />
              </div>
            </motion.div>
          )}
          
          {connectionStatus === "error" && (
            <MicOff className="w-12 h-12 text-red-400" />
          )}
        </div>
      </motion.button>
    </div>
  );
}

