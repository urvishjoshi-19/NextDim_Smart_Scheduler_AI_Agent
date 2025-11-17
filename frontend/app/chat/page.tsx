"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import VoiceAssistant from "@/components/VoiceAssistant";

function ChatContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check URL for user_id from OAuth callback
    const urlUserId = searchParams.get("user_id");
    const authStatus = searchParams.get("auth");

    if (authStatus === "success" && urlUserId) {
      // Store user_id in localStorage
      localStorage.setItem("user_id", urlUserId);
      setUserId(urlUserId);
      setLoading(false);
      
      // Clean up URL
      router.replace("/chat");
    } else {
      // Check if user_id exists in localStorage
      const storedUserId = localStorage.getItem("user_id");
      
      if (storedUserId) {
        setUserId(storedUserId);
        setLoading(false);
      } else {
        // No authentication - redirect to login
        router.push("/");
      }
    }
  }, [searchParams, router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-amoled">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-primary mx-auto mb-4"></div>
          <p className="text-gray-400">Loading...</p>
        </div>
      </div>
    );
  }

  if (!userId) {
    return null; // Will redirect in useEffect
  }

  return <VoiceAssistant userId={userId} />;
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-amoled">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-primary mx-auto mb-4"></div>
            <p className="text-gray-400">Loading...</p>
          </div>
        </div>
      }
    >
      <ChatContent />
    </Suspense>
  );
}

