"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import BookingConfirmation from "./BookingConfirmation";
import ConversationDisplay from "./ConversationDisplay";
import StateIndicator from "./StateIndicator";

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
}

interface WorkflowState {
  duration?: number;
  date?: string;
  slots_found?: number;
}

type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error";
type VoiceState = "idle" | "listening" | "thinking" | "speaking";

const BACKEND_WS_URL = process.env.NEXT_PUBLIC_WS_URL || "wss://smart-scheduler-ai-lhorvsygpa-uc.a.run.app";

interface VoiceAssistantProps {
  userId: string;
}

export default function VoiceAssistant({ userId }: VoiceAssistantProps) {
  const WS_URL = `${BACKEND_WS_URL}/ws/voice/${userId}`;
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentTranscript, setCurrentTranscript] = useState<string>("");
  const [showBookingConfirmation, setShowBookingConfirmation] = useState(false);
  const [bookingDetails, setBookingDetails] = useState<any>(null);
  const [conversationStarted, setConversationStarted] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const activeAudioSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const isPlayingAudioRef = useRef<boolean>(false);
  const hasUserInteractedRef = useRef<boolean>(false);
  const greetingSentRef = useRef<boolean>(false);
  const audioCompletionTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  
  // Audio streaming refs (for sending audio to backend)
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const isStreamingAudioRef = useRef(false);

  // Helper function to convert Float32Array to Int16Array
  const float32ToInt16 = useCallback((float32Array: Float32Array): Int16Array => {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array;
  }, []);

    const startAudioStreaming = async () => {
    console.log("🎤 [START AUDIO] startAudioStreaming() called");
    console.log(`   Current state: streaming=${isStreamingAudioRef.current}`);
    
    if (isStreamingAudioRef.current) {
      console.log("   ⚠️ Already streaming audio - returning");
      return;
    }
    
    try {
      console.log(`   🔍 Checking for existing context...`);
      console.log(`      audioContext: ${!!audioContextRef.current}`);
      console.log(`      audioStream: ${!!audioStreamRef.current}`);
      console.log(`      processor: ${!!processorRef.current}`);
      
      // Check if we already have an active context - if so, just resume streaming
      if (audioContextRef.current && audioStreamRef.current && processorRef.current) {
        console.log("   🔄 [STREAM] ✅ Context exists - RESUMING existing audio stream");
        isStreamingAudioRef.current = true;
        console.log("   ✅ [STREAM] Flag set to TRUE - processor will now send data");
        console.log(`   ✅ [STREAM] Processor callback checks: isStreamingAudioRef.current = ${isStreamingAudioRef.current}`);
        return;
      }
      
      console.log("   🎙️ [STREAM] No existing context - Initializing NEW MediaStream for audio capture...");
      
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 16000,
        },
      });
      
      audioStreamRef.current = stream;
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;
      
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(2048, 1, 1);
      processorRef.current = processor;
      
      let audioChunkCounter = 0;
      processor.onaudioprocess = (e) => {
        audioChunkCounter++;
        const shouldLog = audioChunkCounter % 100 === 0; // Log every 100th chunk to avoid spam
        
        if (shouldLog) {
          console.log(`🎤 [PROCESSOR] Callback fired (chunk ${audioChunkCounter})`);
          console.log(`   WS ready: ${wsRef.current?.readyState === WebSocket.OPEN}`);
          console.log(`   Streaming flag: ${isStreamingAudioRef.current}`);
        }
        
        if (wsRef.current?.readyState === WebSocket.OPEN && isStreamingAudioRef.current) {
          const inputData = e.inputBuffer.getChannelData(0);
          const sourceSampleRate = audioContext.sampleRate;
          const targetSampleRate = 16000;
          
          let processedData = inputData;
          
          // Resample if needed
          if (sourceSampleRate !== targetSampleRate) {
            const resampleRatio = targetSampleRate / sourceSampleRate;
            const newLength = Math.floor(inputData.length * resampleRatio);
            const downsampled = new Float32Array(newLength);
            
            const step = 1 / resampleRatio;
            for (let i = 0; i < newLength; i++) {
              downsampled[i] = inputData[Math.floor(i * step)];
            }
            
            processedData = downsampled;
          }
          
          // Convert to Int16
          const pcmData = new Int16Array(processedData.length);
          for (let i = 0; i < processedData.length; i++) {
            const s = Math.max(-1, Math.min(1, processedData[i]));
            pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
          }
          
          if (shouldLog) {
            console.log(`   ✅ Sending ${pcmData.length} samples to backend`);
          }
          
                    // This allows Deepgram to detect when speech ends
          wsRef.current.send(pcmData.buffer);
        } else if (shouldLog) {
          console.log(`   ⏸️ Skipping send (paused or WS not ready)`);
        }
      };
      
      source.connect(processor);
      processor.connect(audioContext.destination);
      
      isStreamingAudioRef.current = true;
      console.log("   ✅ [STREAM] Audio streaming ACTIVE - sending to backend");
    } catch (error) {
      console.error("   ❌ [STREAM] Failed to start:", error);
      throw error;
    }
  };

  // Pause streaming audio (keep context alive, just stop processing)
  const stopAudioStreaming = async () => {
    console.log("🛑 [STOP AUDIO] stopAudioStreaming() called");
    console.log(`   Before: isStreamingAudioRef.current = ${isStreamingAudioRef.current}`);
    
    // Just set flag to false - processor keeps running but won't send data
    isStreamingAudioRef.current = false;
    
    console.log(`   After: isStreamingAudioRef.current = ${isStreamingAudioRef.current}`);
    console.log("   ✅ [STREAM] Audio streaming PAUSED (context/processor still alive)");
  };
  
  // Fully cleanup audio (only called on unmount)
  const cleanupAudioCapture = async () => {
    console.log("   🛑 [STREAM] Full cleanup of audio capture...");
    
    isStreamingAudioRef.current = false;
    
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    
    if (audioContextRef.current) {
      await audioContextRef.current.close();
      audioContextRef.current = null;
    }
    
    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach(track => track.stop());
      audioStreamRef.current = null;
    }
    
    console.log("   ✅ [STREAM] Audio capture fully cleaned up");
  };

  
  useEffect(() => {
    connectWebSocket();
    return () => {
      cleanup();
    };
  }, []);

  const connectWebSocket = () => {
    try {
      console.log("🔌 Connecting to WebSocket:", WS_URL);
      setConnectionStatus("connecting");
      
      const ws = new WebSocket(WS_URL);
      
      ws.onopen = () => {
        console.log("✅ WebSocket connected");
        setConnectionStatus("connected");
        wsRef.current = ws;
        
        setMessages([]);
        setCurrentTranscript("");
        setVoiceState("idle");
        setShowBookingConfirmation(false);
        setBookingDetails(null);
        hasUserInteractedRef.current = false;
        greetingSentRef.current = false;
        setConversationStarted(false);
      };
      
      ws.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          const audioData = await event.data.arrayBuffer();
          await playAudio(audioData);
        } else {
          try {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
          } catch (parseError) {
            console.error("Failed to parse WebSocket message:", parseError, event.data);
          }
        }
      };
      
      ws.onerror = (error) => {
        console.error("❌ WebSocket error:", error);
        setConnectionStatus("error");
        addMessage("system", "Connection error. Please refresh the page.");
      };
      
      ws.onclose = (event) => {
        console.log("WebSocket disconnected", event);
        setConnectionStatus("disconnected");
        setVoiceState("idle");
        
        if (!event.wasClean) {
          console.log("Connection lost - attempting reconnect in 3s...");
          setTimeout(() => {
            if (wsRef.current === null || wsRef.current.readyState === WebSocket.CLOSED) {
              connectWebSocket();
            }
          }, 3000);
        }
      };
      
      wsRef.current = ws;
    } catch (error) {
      console.error("Failed to connect:", error);
      setConnectionStatus("error");
      addMessage("system", `Connection failed: ${error}`);
    }
  };

  const handleWebSocketMessage = (data: any) => {
    console.log("📨 Message:", data.type, data);
    
    switch (data.type) {
      case "response":
        console.log("Received response:", data.text);
        
        if (data.text && data.text.trim()) {
          addMessage("assistant", data.text);
        }
        break;
        
      case "transcript":
        if (data.text && data.text.trim()) {
          setCurrentTranscript(data.text);
          // Ensure we're in listening state when we receive transcripts
          if (voiceState === "idle") {
            setVoiceState("listening");
          }
        }
        break;
        
      case "transcript_processing":
        console.log("Transcript being processed:", data.text);
        addMessage("user", data.text);
        setCurrentTranscript("");
        break;
        
      case "audio_start":
        console.log("🔊 AI started speaking");
        stopAllAudio();
        setVoiceState("speaking");
        isPlayingAudioRef.current = true;
        
        // Clear any existing audio completion timeout
        if (audioCompletionTimeoutRef.current) {
          clearTimeout(audioCompletionTimeoutRef.current);
          audioCompletionTimeoutRef.current = null;
          console.log("Cleared previous audio completion timeout");
        }
        
        if (playbackContextRef.current) {
          if (playbackContextRef.current.state === "suspended") {
            playbackContextRef.current.resume().then(() => {
              nextPlayTimeRef.current = playbackContextRef.current!.currentTime + 0.05;
            });
          } else {
            nextPlayTimeRef.current = playbackContextRef.current.currentTime + 0.05;
          }
        }
        break;
        
      case "audio_end":
        console.log("🔇 AI audio streaming complete - waiting for playback to finish");
        isPlayingAudioRef.current = false;
        
        // Wait for all audio buffers to finish playing
        // Calculate expected playback time based on buffered audio
        const estimatedPlaybackTime = 5000; // 5 seconds buffer
        console.log(`⏰ Setting ${estimatedPlaybackTime}ms timeout for audio completion`);
        
        audioCompletionTimeoutRef.current = setTimeout(() => {
          console.log("✅ Audio playback complete - notifying backend");
          
          // Notify backend that audio playback is complete
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            try {
              wsRef.current.send(JSON.stringify({
                type: "audio_playback_complete"
              }));
              console.log("📤 Sent audio_playback_complete message to backend");
            } catch (error) {
              console.error("Failed to send audio_playback_complete:", error);
            }
          } else {
            console.warn("⚠️ WebSocket not ready to send audio_playback_complete");
          }
          
          // Clean up audio sources
          activeAudioSourcesRef.current = activeAudioSourcesRef.current.filter(source => {
            return source.context.state !== 'closed';
          });
          
          // Clear timeout ref
          audioCompletionTimeoutRef.current = null;
        }, estimatedPlaybackTime);
        break;
        
      case "state_change":
                console.log("📊 State change from backend:", data.state);
        console.log(`   📌 Current streaming: ${isStreamingAudioRef.current}, WS connected: ${wsRef.current?.readyState === WebSocket.OPEN}`);
        console.log(`   📌 Context: ${!!audioContextRef.current}, Stream: ${!!audioStreamRef.current}, Processor: ${!!processorRef.current}`);
        
        setVoiceState(data.state);
        
        // Ensure conversation is marked as started when we receive meaningful states
        if ((data.state === "thinking" || data.state === "speaking" || data.state === "listening") && !conversationStarted) {
          console.log("🎬 Conversation now active - enabling state indicator");
          setConversationStarted(true);
        }
        
        // Log state updates for UX visibility
        if (data.state === "thinking") {
          console.log("🤔 AI is THINKING - showing thinking animation");
        } else if (data.state === "speaking") {
          console.log("🗣️ AI is SPEAKING - showing speaking animation");
        }
        
        // 🎤 Manage audio streaming based on state
        if (data.state === "thinking" || data.state === "speaking") {
          console.log("🛑 Stopping audio streaming (AI is active)");
          stopAudioStreaming();
        } else if (data.state === "idle" || data.state === "listening") {
                    // We should always resume when backend says it's safe, regardless of conversationStarted state
          console.log(`🔍 Should resume? !streaming: ${!isStreamingAudioRef.current}, WS ready: ${wsRef.current?.readyState === WebSocket.OPEN}`);
          
          if (!isStreamingAudioRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
            console.log("🎤 ✅ YES - Calling startAudioStreaming() to resume");
            startAudioStreaming().catch(err => {
              console.error("❌ Failed to restart audio streaming:", err);
            });
          } else {
            console.log(`⚠️ NO - Not resuming. Streaming: ${isStreamingAudioRef.current}, WS ready: ${wsRef.current?.readyState === WebSocket.OPEN}`);
          }
        }
        break;
      
      case "status":
        // Legacy support
        if (data.status === "thinking") {
          setVoiceState("thinking");
        } else if (data.status === "idle") {
          setVoiceState("idle");
        }
        break;
        
      case "workflow":
        handleWorkflowMessage(data);
        break;
        
      case "error":
        console.error("Backend error:", data.message);
        addMessage("system", `Error: ${data.message}`);
        setVoiceState("idle");
        break;
        
      case "log":
        console.log(`[Backend ${data.level}]:`, data.message);
        break;
    }
  };

  const handleWorkflowMessage = (data: any) => {
    if (data.booking_confirmed === true && data.booking_details) {
      console.log("✅ Booking confirmed:", data.booking_details);
      
      setTimeout(() => {
        setBookingDetails({
          title: data.booking_details.title || "Meeting Scheduled",
          date: data.booking_details.date,
          duration: data.booking_details.duration,
          time: data.booking_details.time
        });
        setShowBookingConfirmation(true);
        
        setTimeout(() => {
          setShowBookingConfirmation(false);
        }, 5000);
      }, 500);
    }
  };

  const addMessage = (role: Message["role"], content: string) => {
    if (!content || content.trim().length === 0) {
      return;
    }
    
    setMessages((prev) => {
      const lastTwo = prev.slice(-2);
      const isDuplicate = lastTwo.some(
        (msg) => 
          msg.role === role && 
          msg.content.trim().toLowerCase() === content.trim().toLowerCase()
      );
      
      if (isDuplicate) {
        return prev;
      }
      
      const newMessage = {
        role,
        content: content.trim(),
        timestamp: Date.now(),
      };
      
      return [...prev, newMessage];
    });
  };

  const startConversation = async () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.error("WebSocket not connected");
      return;
    }

    try {
      hasUserInteractedRef.current = true;
      
      // Initialize audio context for playback
      if (!playbackContextRef.current || playbackContextRef.current.state === "closed") {
        playbackContextRef.current = new AudioContext();
        
        if (playbackContextRef.current.state === "suspended") {
          await playbackContextRef.current.resume();
        }
        
        nextPlayTimeRef.current = playbackContextRef.current.currentTime;
      }
      
      setConversationStarted(true);
      setVoiceState("idle");
      
            console.log("✅ Ready to listen - Deepgram will detect when you speak");
      await startAudioStreaming();
      
      // Request greeting from backend
      if (!greetingSentRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        greetingSentRef.current = true;
        wsRef.current.send(JSON.stringify({ type: "ready_for_greeting" }));
        setVoiceState("thinking");
      }
    } catch (error) {
      console.error("Failed to start conversation:", error);
      addMessage("system", "Failed to start conversation. Please refresh and try again.");
    }
  };

  const stopAllAudio = () => {
    console.log("🔇 Stopping all audio playback");
    
    activeAudioSourcesRef.current.forEach((source) => {
      try {
        source.stop();
        source.disconnect();
      } catch (e) {
        // Source might already be stopped
      }
    });
    
    activeAudioSourcesRef.current = [];
    
    if (playbackContextRef.current) {
      nextPlayTimeRef.current = playbackContextRef.current.currentTime;
    }
    
    isPlayingAudioRef.current = false;
  };

  const playAudio = async (audioData: ArrayBuffer) => {
    try {
      if (!audioData || audioData.byteLength === 0) {
        console.warn("⚠️ Empty audio chunk");
        return;
      }
      
      if (!playbackContextRef.current || playbackContextRef.current.state === "closed") {
        console.warn("AudioContext not initialized");
        playbackContextRef.current = new AudioContext();
        nextPlayTimeRef.current = playbackContextRef.current.currentTime + 0.05;
      }

      const playbackContext = playbackContextRef.current;

      if (playbackContext.state === "suspended") {
        console.log("⚠️ Resuming AudioContext");
        await playbackContext.resume();
        nextPlayTimeRef.current = playbackContext.currentTime + 0.05;
      }

      // Convert PCM16 to Float32
      const int16Array = new Int16Array(audioData);
      
      if (int16Array.length < 100) {
        console.warn(`⚠️ Very small audio chunk (${int16Array.length} samples)`);
      }
      
      const float32Array = new Float32Array(int16Array.length);
      
      const INT16_MAX = 32767.0;
      const INT16_MIN = -32768.0;
      
      for (let i = 0; i < int16Array.length; i++) {
        const sample = int16Array[i];
        if (sample < 0) {
          float32Array[i] = sample / -INT16_MIN;
        } else {
          float32Array[i] = sample / INT16_MAX;
        }
      }
      
      const hasAudio = float32Array.some(sample => Math.abs(sample) > 0.001);
      if (!hasAudio) {
        console.warn("⚠️ Audio chunk contains only silence");
        return;
      }

      const sourceSampleRate = 16000;
      const audioBuffer = playbackContext.createBuffer(
        1,
        float32Array.length,
        sourceSampleRate
      );
      audioBuffer.getChannelData(0).set(float32Array);

      const currentTime = playbackContext.currentTime;
      
      if (nextPlayTimeRef.current < currentTime) {
        nextPlayTimeRef.current = currentTime + 0.001;
      }

      const source = playbackContext.createBufferSource();
      source.buffer = audioBuffer;
      source.playbackRate.value = 1.0;
      
      const gainNode = playbackContext.createGain();
      gainNode.gain.value = 1.0;
      
      source.connect(gainNode);
      gainNode.connect(playbackContext.destination);
      
      activeAudioSourcesRef.current.push(source);
      
      source.onended = () => {
        const index = activeAudioSourcesRef.current.indexOf(source);
        if (index > -1) {
          activeAudioSourcesRef.current.splice(index, 1);
        }
      };
      
      const startTime = nextPlayTimeRef.current;
      const actualStartTime = Math.max(startTime, currentTime);
      
      source.start(actualStartTime);

      const chunkDuration = audioBuffer.duration;
      nextPlayTimeRef.current = actualStartTime + chunkDuration;
      
    } catch (error) {
      console.error("❌ Audio playback error:", error);
      if (playbackContextRef.current) {
        nextPlayTimeRef.current = playbackContextRef.current.currentTime;
      }
      isPlayingAudioRef.current = false;
      setVoiceState("idle");
    }
  };

  const cleanup = () => {
    stopAllAudio();
    
    // Fully cleanup audio capture (only on unmount)
    cleanupAudioCapture();
    
    // Clear audio completion timeout
    if (audioCompletionTimeoutRef.current) {
      clearTimeout(audioCompletionTimeoutRef.current);
      audioCompletionTimeoutRef.current = null;
      console.log("Cleared audio completion timeout during cleanup");
    }
    
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN || 
          wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close(1000, "Component unmount");
      }
      wsRef.current = null;
    }
    
    if (playbackContextRef.current && playbackContextRef.current.state !== 'closed') {
      playbackContextRef.current.close();
      playbackContextRef.current = null;
    }
    
    nextPlayTimeRef.current = 0;
    activeAudioSourcesRef.current = [];
    isPlayingAudioRef.current = false;
    hasUserInteractedRef.current = false;
    greetingSentRef.current = false;
    setConversationStarted(false);
  };

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center p-4 overflow-hidden">
      {/* Animated Background Elements */}
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
      <div className="relative z-10 w-full max-w-4xl mx-auto flex flex-col items-center">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
          className="text-center mb-12"
        >
          <h1 className="text-5xl md:text-6xl font-bold mb-4 text-gradient">
            NextDimension AI
          </h1>
          <p className="text-gray-400 text-lg">
            Just speak - no buttons needed
          </p>
        </motion.div>

        {/* Start Button (only shown before conversation) */}
        {connectionStatus === "connected" && !conversationStarted && (
          <motion.button
            onClick={startConversation}
            className="px-8 py-4 rounded-2xl bg-gradient-purple text-white font-semibold text-lg shadow-glow-purple-lg hover:shadow-glow-purple-xl transition-all duration-300"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            Start Conversation
          </motion.button>
        )}

        {/* State Indicator (shown after conversation starts) */}
        {conversationStarted && (
          <StateIndicator 
            state={voiceState}
          />
        )}

        {/* Current Transcript (while listening or thinking) */}
        <AnimatePresence>
          {currentTranscript && conversationStarted && (
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="mt-6 glass-strong rounded-2xl p-4 max-w-md"
            >
              <p className="text-purple-light text-sm font-medium mb-1">
                {voiceState === "thinking" ? "Processing..." : "You're saying..."}
              </p>
              <p className="text-white">{currentTranscript}</p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Conversation Display */}
        <ConversationDisplay messages={messages} />
      </div>

      {/* Booking Confirmation Modal */}
      <AnimatePresence>
        {showBookingConfirmation && bookingDetails && (
          <BookingConfirmation
            details={bookingDetails}
            onClose={() => setShowBookingConfirmation(false)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
