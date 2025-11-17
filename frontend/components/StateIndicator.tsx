"use client";

import { motion } from "framer-motion";
import { Mic, Loader2, Volume2 } from "lucide-react";

export type VoiceState = "idle" | "listening" | "thinking" | "speaking";

interface StateIndicatorProps {
  state: VoiceState;
}

export default function StateIndicator({ state }: StateIndicatorProps) {
  const getIndicatorConfig = () => {
    switch (state) {
      case "idle":
        return {
          color: "purple",
          bgColor: "bg-purple-primary/20",
          borderColor: "border-purple-primary/30",
          icon: <Mic className="w-12 h-12 text-purple-light" />,
          animation: "pulse",
          showRipples: false,
          text: "I'm listening - just speak anytime"
        };
        
      case "listening":
        return {
          color: "blue",
          bgColor: "bg-blue-500/20",
          borderColor: "border-blue-500/50",
          icon: <Mic className="w-12 h-12 text-blue-400" />,
          animation: "listening",
          showRipples: true,
          text: "Listening..."
        };
        
      case "thinking":
        return {
          color: "gradient",
          bgColor: "bg-gradient-to-r from-purple-primary to-pink-500",
          borderColor: "border-purple-primary/50",
          icon: <div className="custom-loader" />,
          animation: "thinking",
          showRipples: false,
          text: "AI is thinking..."
        };
        
      case "speaking":
        return {
          color: "green",
          bgColor: "bg-green-500/20",
          borderColor: "border-green-500/50",
          icon: <Volume2 className="w-12 h-12 text-green-400" />,
          animation: "equalizer",
          showRipples: false,
          text: "AI is speaking..."
        };
        
      default:
        return {
          color: "gray",
          bgColor: "bg-gray-500/20",
          borderColor: "border-gray-500/30",
          icon: <Mic className="w-12 h-12 text-gray-400" />,
          animation: "none",
          showRipples: false,
          text: ""
        };
    }
  };
  
  const config = getIndicatorConfig();
  
  return (
    <div className="flex flex-col items-center justify-center gap-6">
      {/* Visual Indicator */}
      <div className="relative flex items-center justify-center">
        {/* Ripple effect for listening states */}
        {config.showRipples && (
          <>
            <motion.div
              className={`absolute w-48 h-48 rounded-full border-2 ${config.borderColor}`}
              initial={{ scale: 1, opacity: 0.8 }}
              animate={{ scale: 1.8, opacity: 0 }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: "easeOut",
              }}
            />
            <motion.div
              className={`absolute w-48 h-48 rounded-full border-2 ${config.borderColor}`}
              initial={{ scale: 1, opacity: 0.8 }}
              animate={{ scale: 1.8, opacity: 0 }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: "easeOut",
                delay: 0.7,
              }}
            />
          </>
        )}
        
        {/* Background glow */}
        <motion.div
          className={`absolute w-40 h-40 rounded-full ${config.bgColor} blur-2xl`}
          animate={
            config.animation === "pulse"
              ? {
                  scale: [1, 1.2, 1],
                  opacity: [0.5, 0.8, 0.5],
                }
              : {}
          }
          transition={{
            duration: 2,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        />
        
        {/* Main indicator */}
        <motion.div
          className={`
            relative z-10 w-32 h-32 rounded-full
            flex items-center justify-center
            glass-strong ${config.borderColor} border-2
          `}
          animate={
            config.animation === "rotate"
              ? { rotate: 360 }
              : config.animation === "pulse"
              ? { scale: [1, 1.05, 1] }
              : config.animation === "thinking"
              ? {} // Custom loader handles its own animation
              : {}
          }
          transition={
            config.animation === "rotate"
              ? { duration: 2, repeat: Infinity, ease: "linear" }
              : config.animation === "pulse"
              ? { duration: 2, repeat: Infinity }
              : config.animation === "thinking"
              ? {} // Custom loader handles its own animation
              : {}
          }
        >
          {/* Equalizer for speaking state */}
          {config.animation === "equalizer" ? (
            <div className="flex items-center gap-1">
              {[0, 0.1, 0.2].map((delay) => (
                <motion.div
                  key={delay}
                  className="w-2 h-8 bg-green-400 rounded-full"
                  animate={{ height: [32, 16, 32] }}
                  transition={{ duration: 0.5, repeat: Infinity, delay }}
                />
              ))}
            </div>
          ) : (
            config.icon
          )}
        </motion.div>
        
      </div>
      
      {/* Status Text */}
      <motion.div
        className="text-center"
        animate={{ opacity: [0.7, 1, 0.7] }}
        transition={{ duration: 2, repeat: Infinity }}
      >
        <p className="text-sm text-gray-400">
          {config.text}
        </p>
      </motion.div>
      
      {/* Custom Loader Styles */}
      <style jsx>{`
        .custom-loader {
          transform: rotateZ(45deg);
          perspective: 1000px;
          border-radius: 50%;
          width: 48px;
          height: 48px;
          color: #fff;
        }
        
        .custom-loader:before,
        .custom-loader:after {
          content: '';
          display: block;
          position: absolute;
          top: 0;
          left: 0;
          width: inherit;
          height: inherit;
          border-radius: 50%;
          transform: rotateX(70deg);
          animation: 1s spin linear infinite;
        }
        
        .custom-loader:after {
          color: #FF3D00;
          transform: rotateY(70deg);
          animation-delay: .4s;
        }

        @keyframes spin {
          0%,
          100% {
            box-shadow: .2em 0px 0 0px currentcolor;
          }
          12% {
            box-shadow: .2em .2em 0 0 currentcolor;
          }
          25% {
            box-shadow: 0 .2em 0 0px currentcolor;
          }
          37% {
            box-shadow: -.2em .2em 0 0 currentcolor;
          }
          50% {
            box-shadow: -.2em 0 0 0 currentcolor;
          }
          62% {
            box-shadow: -.2em -.2em 0 0 currentcolor;
          }
          75% {
            box-shadow: 0px -.2em 0 0 currentcolor;
          }
          87% {
            box-shadow: .2em -.2em 0 0 currentcolor;
          }
        }
      `}</style>
    </div>
  );
}

