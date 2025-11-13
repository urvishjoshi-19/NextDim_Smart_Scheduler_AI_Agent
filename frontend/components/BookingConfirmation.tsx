"use client";

import { motion } from "framer-motion";
import { CheckCircle2, Calendar, Clock, X } from "lucide-react";
import { useEffect } from "react";

interface BookingDetails {
  title: string;
  date?: string;
  time?: string;
  duration?: number;
  slots?: number;
}

interface BookingConfirmationProps {
  details: BookingDetails;
  onClose: () => void;
}

export default function BookingConfirmation({
  details,
  onClose,
}: BookingConfirmationProps) {
  // Confetti particles
  const particles = Array.from({ length: 20 }, (_, i) => ({
    id: i,
    x: Math.random() * 400 - 200,
    y: Math.random() * -300 - 50,
    rotation: Math.random() * 360,
    scale: Math.random() * 0.5 + 0.5,
    delay: Math.random() * 0.5,
  }));

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.8, opacity: 0, y: 20 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.8, opacity: 0, y: 20 }}
        transition={{ type: "spring", stiffness: 300, damping: 25 }}
        className="relative glass-strong rounded-3xl p-8 max-w-md w-full shadow-glow-purple-lg overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <motion.button
          whileHover={{ scale: 1.1, rotate: 90 }}
          whileTap={{ scale: 0.9 }}
          onClick={onClose}
          className="absolute top-4 right-4 w-8 h-8 rounded-full glass flex items-center justify-center hover:bg-white/10 transition-colors"
        >
          <X className="w-4 h-4 text-gray-400" />
        </motion.button>

        {/* Confetti particles */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          {particles.map((particle) => (
            <motion.div
              key={particle.id}
              className="absolute top-1/2 left-1/2 w-2 h-2 bg-purple-light rounded-full"
              initial={{
                x: 0,
                y: 0,
                opacity: 1,
                scale: particle.scale,
                rotate: 0,
              }}
              animate={{
                x: particle.x,
                y: particle.y,
                opacity: 0,
                rotate: particle.rotation,
              }}
              transition={{
                duration: 1.5,
                delay: particle.delay,
                ease: "easeOut",
              }}
            />
          ))}
        </div>

        {/* Success icon */}
        <motion.div
          className="flex justify-center mb-6"
          initial={{ scale: 0, rotate: -180 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{
            type: "spring",
            stiffness: 200,
            damping: 15,
            delay: 0.2,
          }}
        >
          <motion.div
            className="relative"
            animate={{
              rotate: [0, 10, -10, 0],
            }}
            transition={{
              duration: 0.5,
              delay: 0.5,
              ease: "easeInOut",
            }}
          >
            {/* Glow effect */}
            <motion.div
              className="absolute inset-0 bg-green-500/30 rounded-full blur-xl"
              animate={{
                scale: [1, 1.3, 1],
                opacity: [0.5, 0.8, 0.5],
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: "easeInOut",
              }}
            />
            <CheckCircle2 className="w-20 h-20 text-green-400 relative z-10" />
          </motion.div>
        </motion.div>

        {/* Success message */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="text-center mb-6"
        >
          <h2 className="text-3xl font-bold text-white mb-2">
            Meeting Booked!
          </h2>
          <p className="text-gray-300">
            Your meeting has been successfully scheduled
          </p>
        </motion.div>

        {/* Details */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="space-y-4"
        >
          {/* Title */}
          <div className="glass rounded-2xl p-4">
            <p className="text-sm text-gray-400 mb-1">Meeting</p>
            <p className="text-white font-medium">{details.title}</p>
          </div>

          {/* Date, Time & Duration */}
          <div className="grid grid-cols-2 gap-3">
            {details.date && (
              <motion.div
                className="glass rounded-2xl p-4"
                whileHover={{ scale: 1.02 }}
                transition={{ type: "spring", stiffness: 400 }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Calendar className="w-4 h-4 text-purple-light" />
                  <p className="text-sm text-gray-400">Date & Time</p>
                </div>
                <p className="text-white font-medium text-sm">
                  {details.date}
                  {details.time && (
                    <>
                      <br />
                      <span className="text-purple-light">{details.time}</span>
                    </>
                  )}
                </p>
              </motion.div>
            )}

            {details.duration && (
              <motion.div
                className="glass rounded-2xl p-4"
                whileHover={{ scale: 1.02 }}
                transition={{ type: "spring", stiffness: 400 }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Clock className="w-4 h-4 text-purple-light" />
                  <p className="text-sm text-gray-400">Duration</p>
                </div>
                <p className="text-white font-medium text-sm">
                  {details.duration} min
                </p>
              </motion.div>
            )}
          </div>
        </motion.div>

        {/* Success wave animation */}
        <motion.div
          className="absolute bottom-0 left-0 right-0 h-1 bg-gradient-purple"
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 1, delay: 0.5 }}
        />
      </motion.div>
    </motion.div>
  );
}

