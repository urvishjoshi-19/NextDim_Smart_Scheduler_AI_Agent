"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, MicOff, Loader2 } from "lucide-react";
import BookingConfirmation from "./BookingConfirmation";
import ConversationDisplay from "./ConversationDisplay";
import MicButton from "./MicButton";

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

const USER_ID = "100756814331326833034";
const WS_URL = `ws://localhost:8000/ws/voice/${USER_ID}`;

export default function VoiceAssistant() {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentTranscript, setCurrentTranscript] = useState<string>("");
  const [showBookingConfirmation, setShowBookingConfirmation] = useState(false);
  const [bookingDetails, setBookingDetails] = useState<any>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [conversationStarted, setConversationStarted] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const activeAudioSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const isPlayingAudioRef = useRef<boolean>(false);
  const isWaitingForTranscriptRef = useRef<boolean>(false);
  const currentUserMessageIndexRef = useRef<number>(-1);
  const hasUserInteractedRef = useRef<boolean>(false);
  const greetingSentRef = useRef<boolean>(false);

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
        console.log("WebSocket connected");
        setConnectionStatus("connected");
        wsRef.current = ws;
        
        setMessages([]);
        setCurrentTranscript("");
        setVoiceState("idle");
        setIsRecording(false);
        setShowBookingConfirmation(false);
        setBookingDetails(null);
        isWaitingForTranscriptRef.current = false;
        currentUserMessageIndexRef.current = -1;
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
          console.log("Connection lost unexpectedly - attempting to reconnect in 3 seconds...");
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
        }
        break;
        
      case "transcript_processing":
        console.log("Transcript being processed:", data.text);
        addMessage("user", data.text);
        isWaitingForTranscriptRef.current = false;
        currentUserMessageIndexRef.current = -1;
        setCurrentTranscript("");
        break;
        
      case "audio_start":
        stopAllAudio();
        setVoiceState("speaking");
        isPlayingAudioRef.current = true;
        
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
        setVoiceState("idle");
        isPlayingAudioRef.current = false;
        activeAudioSourcesRef.current = activeAudioSourcesRef.current.filter(source => {
          return source.context.state !== 'closed';
        });
        break;
        
      case "status":
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
        isWaitingForTranscriptRef.current = false;
        break;
        
      case "log":
        console.log(`[Backend ${data.level}]:`, data.message);
        break;
    }
  };

  const handleWorkflowMessage = (data: any) => {
    if (data.booking_confirmed === true && data.booking_details) {
      console.log("Booking confirmed, showing confirmation dialog", data.booking_details);
      
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
      
      if (role === "user") {
        currentUserMessageIndexRef.current = prev.length;
      }
      
      return [...prev, newMessage];
    });
  };

  const toggleRecording = async () => {
    if (isRecording) {
      await stopRecording();
    } else {
      await startRecording();
    }
  };

  const startConversation = async () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.error("WebSocket not connected");
      return;
    }

    try {
      hasUserInteractedRef.current = true;
      
      if (!playbackContextRef.current || playbackContextRef.current.state === "closed") {
        playbackContextRef.current = new AudioContext();
        
        if (playbackContextRef.current.state === "suspended") {
          await playbackContextRef.current.resume();
        }
        
        nextPlayTimeRef.current = playbackContextRef.current.currentTime;
      }
      
      setConversationStarted(true);
      
      if (!greetingSentRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        greetingSentRef.current = true;
        const greetingRequest = { type: "ready_for_greeting" };
        wsRef.current.send(JSON.stringify(greetingRequest));
        setVoiceState("thinking");
      }
    } catch (error) {
      console.error("Failed to start conversation:", error);
      addMessage("system", "Failed to start conversation. Please refresh and try again.");
    }
  };

  const startRecording = async () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.error("WebSocket not connected");
      return;
    }

    try {
      if (isPlayingAudioRef.current) {
        stopAllAudio();
        setVoiceState("idle");
      }

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
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          const inputData = e.inputBuffer.getChannelData(0);
          const sourceSampleRate = audioContext.sampleRate;
          const targetSampleRate = 16000;
          
          let processedData = inputData;
          
          if (sourceSampleRate !== targetSampleRate) {
            const resampleRatio = targetSampleRate / sourceSampleRate;
            const newLength = Math.floor(inputData.length * resampleRatio);
            const downsampled = new Float32Array(newLength);
            
            for (let i = 0; i < newLength; i++) {
              const sourceIndex = i / resampleRatio;
              const index0 = Math.floor(sourceIndex);
              const index1 = Math.min(index0 + 1, inputData.length - 1);
              const fraction = sourceIndex - index0;
              
              downsampled[i] =
                inputData[index0] * (1 - fraction) +
                inputData[index1] * fraction;
            }
            
            processedData = downsampled;
          }
          
          const pcmData = new Int16Array(processedData.length);
          for (let i = 0; i < processedData.length; i++) {
            const s = Math.max(-1, Math.min(1, processedData[i]));
            pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }
          
          wsRef.current.send(pcmData.buffer);
        }
      };

      source.connect(processor);
      processor.connect(audioContext.destination);

      setIsRecording(true);
      setVoiceState("listening");
      setCurrentTranscript("");
      isWaitingForTranscriptRef.current = true;
    } catch (error) {
      console.error("Failed to start recording:", error);
      addMessage("system", "Failed to access microphone. Please allow microphone access.");
    }
  };

  const stopRecording = async () => {
    console.log("🛑 Stopping recording...");
    
    // Stop audio processing
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    
    if (audioContextRef.current) {
      await audioContextRef.current.close();
      audioContextRef.current = null;
    }
    
    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach((track) => track.stop());
      audioStreamRef.current = null;
    }

    // Send stop signal to backend to process transcript
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "stop_speaking" }));
      console.log("📤 Sent stop_speaking signal to backend");
    }

    setIsRecording(false);
    setVoiceState("thinking");
    // Keep currentTranscript visible until processing starts
    
    console.log("🛑 Recording stopped, waiting for processing...");
  };

  const stopAllAudio = () => {
    console.log("🔇 Stopping all audio playback and clearing queue");
    
    // Stop all active audio sources
    activeAudioSourcesRef.current.forEach((source) => {
      try {
        source.stop();
        source.disconnect();
      } catch (e) {
        // Source might already be stopped
      }
    });
    
    // Clear the array
    activeAudioSourcesRef.current = [];
    
    // Reset playback timing to current time
    if (playbackContextRef.current) {
      nextPlayTimeRef.current = playbackContextRef.current.currentTime;
      console.log("🔇 Reset playback queue to current time");
    }
    
    isPlayingAudioRef.current = false;
  };

  const playAudio = async (audioData: ArrayBuffer) => {
    try {
      // Validate audio data
      if (!audioData || audioData.byteLength === 0) {
        console.warn("⚠️ Received empty audio chunk, skipping");
        return;
      }
      
      // Ensure we have AudioContext (should be created on first user interaction)
      if (!playbackContextRef.current || playbackContextRef.current.state === "closed") {
        console.warn("AudioContext not initialized - creating now (this should have been done on user interaction)");
        playbackContextRef.current = new AudioContext();
        nextPlayTimeRef.current = playbackContextRef.current.currentTime + 0.05;
      }

      const playbackContext = playbackContextRef.current;

      // Resume if suspended (browser autoplay policy)
      if (playbackContext.state === "suspended") {
        console.log("⚠️ AudioContext suspended - attempting to resume");
        await playbackContext.resume();
        // Reset timing to current time when resuming from suspension
        nextPlayTimeRef.current = playbackContext.currentTime + 0.05;
        console.log("🔊 AudioContext resumed");
      }

      // Convert PCM16 to Float32 with improved normalization
      const int16Array = new Int16Array(audioData);
      
      // Validate chunk size - too small chunks can cause issues
      if (int16Array.length < 100) {
        console.warn(`⚠️ Very small audio chunk received (${int16Array.length} samples), may cause distortion`);
      }
      
      const float32Array = new Float32Array(int16Array.length);
      
      // High-quality PCM16 to Float32 conversion
      // Proper normalization prevents distortion
      const INT16_MAX = 32767.0;
      const INT16_MIN = -32768.0;
      
      for (let i = 0; i < int16Array.length; i++) {
        const sample = int16Array[i];
        // Symmetric normalization to [-1.0, 1.0]
        if (sample < 0) {
          float32Array[i] = sample / -INT16_MIN;
        } else {
          float32Array[i] = sample / INT16_MAX;
        }
      }
      
      // Validate audio data - check for all zeros (silence)
      const hasAudio = float32Array.some(sample => Math.abs(sample) > 0.001);
      if (!hasAudio) {
        console.warn("⚠️ Audio chunk contains only silence, skipping");
        return;
      }

      // Create audio buffer at source sample rate (16kHz from Deepgram)
      const sourceSampleRate = 16000;
      const targetSampleRate = playbackContext.sampleRate;
      
      // CRITICAL FIX: Let the browser handle resampling natively for best quality
      // Offline resampling was causing distortion and timing issues
      // The Web Audio API does high-quality resampling automatically
      const audioBuffer = playbackContext.createBuffer(
        1,
        float32Array.length,
        sourceSampleRate
      );
      audioBuffer.getChannelData(0).set(float32Array);
      
      const finalBuffer = audioBuffer;
      
      if (sourceSampleRate !== targetSampleRate) {
        console.log(`🔊 Browser will resample ${sourceSampleRate}Hz → ${targetSampleRate}Hz automatically`);
      }

      // SIMPLIFIED & ROBUST TIMING for perfect synchronization
      const currentTime = playbackContext.currentTime;
      
      // If nextPlayTime is in the past or stale, reset to current time
      if (nextPlayTimeRef.current < currentTime) {
        // Schedule immediately with minimal buffer
        nextPlayTimeRef.current = currentTime + 0.001; // 1ms minimal buffer
        console.log("🔊 Timing reset: scheduling immediately");
      }

      // Create and configure audio source
      const source = playbackContext.createBufferSource();
      source.buffer = finalBuffer;
      
      // CRITICAL: Ensure playback rate is exactly 1.0 (no speed variation)
      source.playbackRate.value = 1.0;
      
      // Add gain control to prevent clipping and normalize volume
      const gainNode = playbackContext.createGain();
      gainNode.gain.value = 1.0; // Full volume - no reduction needed with proper normalization
      
      source.connect(gainNode);
      gainNode.connect(playbackContext.destination);
      
      // Track active source for interruption handling
      activeAudioSourcesRef.current.push(source);
      
      // Cleanup when chunk finishes
      source.onended = () => {
        const index = activeAudioSourcesRef.current.indexOf(source);
        if (index > -1) {
          activeAudioSourcesRef.current.splice(index, 1);
        }
        console.log(`🔊 Chunk ended (${activeAudioSourcesRef.current.length} remaining)`);
      };
      
      // Schedule and start playback with perfect timing
      const startTime = nextPlayTimeRef.current;
      const currentTimeNow = playbackContext.currentTime;
      
      // Ensure we never schedule in the past
      const actualStartTime = Math.max(startTime, currentTimeNow);
      
      source.start(actualStartTime);

      // Calculate exact next play time for seamless gapless playback
      const chunkDuration = finalBuffer.duration;
      
      // NO GAPS - perfect gapless playback for smooth synthesis
      nextPlayTimeRef.current = actualStartTime + chunkDuration;
      
      const queueLength = activeAudioSourcesRef.current.length;
      console.log(`🔊 Playing chunk #${queueLength + 1}: start=${actualStartTime.toFixed(3)}s, dur=${chunkDuration.toFixed(3)}s, next=${nextPlayTimeRef.current.toFixed(3)}s, rate=${source.playbackRate.value}`);
    } catch (error) {
      console.error("❌ Audio playback error:", error);
      // Reset on error to prevent stuck state
      if (playbackContextRef.current) {
        nextPlayTimeRef.current = playbackContextRef.current.currentTime;
      }
      isPlayingAudioRef.current = false;
      setVoiceState("idle");
    }
  };

  const cleanup = () => {
    stopAllAudio();
    
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN || 
          wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close(1000, "Page refresh or component unmount");
      }
      wsRef.current = null;
    }
    
    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach((track) => track.stop());
      audioStreamRef.current = null;
    }
    
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    
    if (playbackContextRef.current && playbackContextRef.current.state !== 'closed') {
      playbackContextRef.current.close();
      playbackContextRef.current = null;
    }
    
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    
    isWaitingForTranscriptRef.current = false;
    currentUserMessageIndexRef.current = -1;
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
            Your Intelligent Scheduling Assistant
          </p>
        </motion.div>

        {/* Start Conversation Button (shown before conversation starts) */}
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

        {/* Microphone Button (shown after conversation starts) */}
        {conversationStarted && (
          <MicButton
            isRecording={isRecording}
            voiceState={voiceState}
            connectionStatus={connectionStatus}
            onToggle={toggleRecording}
          />
        )}

        {/* Status Text */}
        <motion.div
          className="mt-8 text-center"
          animate={{ opacity: [0.7, 1, 0.7] }}
          transition={{ duration: 2, repeat: Infinity }}
        >
          <p className="text-sm text-gray-400">
            {connectionStatus === "connecting" && "Connecting..."}
            {connectionStatus === "connected" && !conversationStarted && "Ready to begin"}
            {conversationStarted && voiceState === "idle" && !isRecording && "Click mic once to start speaking, click again to send"}
            {conversationStarted && isRecording && "Listening... Click again to send"}
            {voiceState === "thinking" && "AI is thinking..."}
            {voiceState === "speaking" && "AI is speaking..."}
            {connectionStatus === "error" && "Connection error"}
            {connectionStatus === "disconnected" && "Disconnected"}
          </p>
        </motion.div>

        {/* Current Transcript (while speaking) */}
        <AnimatePresence>
          {currentTranscript && (isRecording || voiceState === "thinking") && (
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="mt-6 glass-strong rounded-2xl p-4 max-w-md"
            >
              <p className="text-purple-light text-sm font-medium mb-1">
                {isRecording ? "You're saying..." : "Processing..."}
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

