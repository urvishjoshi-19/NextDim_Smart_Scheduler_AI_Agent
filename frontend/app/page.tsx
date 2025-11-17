"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Mic, Bot, Calendar } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Home() {
  const router = useRouter();
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user is already authenticated
    const userId = localStorage.getItem("user_id");
    
    if (userId) {
      // Verify authentication with backend
      fetch(`${API_URL}/auth/status/${userId}`)
        .then((res) => res.json())
        .then((data) => {
          if (data.authenticated) {
            setIsAuthenticated(true);
            // Redirect to chat
            router.push("/chat");
          } else {
            // Invalid session, clear storage
            localStorage.removeItem("user_id");
            setLoading(false);
          }
        })
        .catch(() => {
          localStorage.removeItem("user_id");
          setLoading(false);
        });
    } else {
      setLoading(false);
    }
  }, [router]);

  const handleLogin = () => {
    // Redirect to backend OAuth login
    window.location.href = `${API_URL}/auth/login`;
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-amoled">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-primary mx-auto mb-4"></div>
          <p className="text-gray-400">Checking authentication...</p>
        </div>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-amoled overflow-hidden">
      {/* Animated Background */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <motion.div
          className="absolute top-1/4 left-1/4 w-96 h-96 bg-purple-primary/20 rounded-full blur-3xl"
          animate={{
            scale: [1, 1.2, 1],
            opacity: [0.3, 0.5, 0.3],
          }}
          transition={{
            duration: 8,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        />
        <motion.div
          className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-purple-dark/20 rounded-full blur-3xl"
          animate={{
            scale: [1.2, 1, 1.2],
            opacity: [0.5, 0.3, 0.5],
          }}
          transition={{
            duration: 8,
            repeat: Infinity,
            ease: "easeInOut",
            delay: 1,
          }}
        />
      </div>

      {/* Main Content */}
      <div className="relative z-10 min-h-screen flex flex-col items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
          className="text-center max-w-2xl"
        >
          <h1 className="text-6xl md:text-7xl font-bold mb-6 text-gradient">
            NextDimension AI
          </h1>
          
          <p className="text-xl md:text-2xl text-gray-300 mb-4">
            Your Intelligent Scheduling Assistant
          </p>
          
          <p className="text-gray-400 mb-12 max-w-xl mx-auto">
            Schedule meetings with natural voice conversations. 
            Powered by AI, seamlessly integrated with Google Calendar.
          </p>

          <motion.button
            onClick={handleLogin}
            className="px-10 py-5 rounded-2xl bg-gradient-purple text-white font-semibold text-lg shadow-glow-purple-lg hover:shadow-glow-purple-xl transition-all duration-300"
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.4 }}
          >
            Sign in with Google
          </motion.button>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.8 }}
            className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-6 text-left"
          >
            <div className="glass-strong rounded-xl p-6">
              <div className="backdrop-blur-md bg-white/10 p-3 rounded-xl shadow-lg inline-block mb-3">
                <Mic className="w-6 h-6 text-white/90" />
              </div>
              <h3 className="text-purple-light font-semibold mb-2">Voice First</h3>
              <p className="text-gray-400 text-sm">
                Natural conversation interface powered by advanced speech recognition
              </p>
            </div>

            <div className="glass-strong rounded-xl p-6">
              <div className="backdrop-blur-md bg-white/10 p-3 rounded-xl shadow-lg inline-block mb-3">
                <Bot className="w-6 h-6 text-white/90" />
              </div>
              <h3 className="text-purple-light font-semibold mb-2">AI Powered</h3>
              <p className="text-gray-400 text-sm">
                Intelligent scheduling that understands context and preferences
              </p>
            </div>

            <div className="glass-strong rounded-xl p-6">
              <div className="backdrop-blur-md bg-white/10 p-3 rounded-xl shadow-lg inline-block mb-3">
                <Calendar className="w-6 h-6 text-white/90" />
              </div>
              <h3 className="text-purple-light font-semibold mb-2">Calendar Sync</h3>
              <p className="text-gray-400 text-sm">
                Seamless integration with your Google Calendar
              </p>
            </div>
          </motion.div>
        </motion.div>
      </div>
    </main>
  );
}
