"use client";

import { ConversationProvider, useConversation, type DisconnectionDetails } from "@elevenlabs/react";
import { useEffect, useRef, useState } from "react";

/**
 * Voice intake call, built on @elevenlabs/react instead of the embed widget.
 *
 * Why: in WebSocket mode the widget's mute keeps the mic open and streams silent
 * frames, and users reported the agent still heard them. Here we connect over
 * WebRTC, where setMuted() mutes the LiveKit mic track (track.mute() sets
 * MediaStreamTrack.enabled = false), so no audio leaves the browser while muted.
 */
export default function VoicePanel({ agentId }: { agentId: string }) {
  return (
    <ConversationProvider>
      <VoiceCall agentId={agentId} />
    </ConversationProvider>
  );
}

function micErrorText(err: unknown): string {
  const name = err instanceof DOMException ? err.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Microphone access is blocked. Allow the microphone for this site (icon in the address bar), then try again.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone found. Plug one in and try again.";
  if (name === "NotReadableError") return "Your microphone is in use by another app. Close it and try again.";
  if (typeof navigator !== "undefined" && !navigator.mediaDevices) return "This browser can't use the microphone on this page.";
  return "Couldn't turn on the microphone. Try again.";
}

function VoiceCall({ agentId }: { agentId: string }) {
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const startRef = useRef<HTMLButtonElement>(null);
  const muteRef = useRef<HTMLButtonElement>(null);

  const { status, isMuted, setMuted, isSpeaking, startSession, endSession } = useConversation({
    onStatusChange: () => setRequesting(false),
    onConnect: () => setError(null),
    onDisconnect: (d: DisconnectionDetails) => {
      if (d.reason === "error") {
        setError("The call dropped. Check your connection and try again.");
        return;
      }
      setError(null); // a non-fatal mid-call error shouldn't linger after a clean hang-up
      setNote(d.reason === "agent" ? "Call ended by SnowTech 311." : "Call ended.");
    },
    onError: () => {
      setRequesting(false);
      setError("Couldn't connect to the voice agent. Check your internet connection and try again.");
    },
  });

  const live = status === "connected";
  const connecting = requesting || status === "connecting";

  // Keep keyboard focus inside the panel when the buttons swap (not on first render).
  // The start button uses aria-disabled rather than disabled so it keeps focus while connecting.
  const wasLive = useRef(live);
  useEffect(() => {
    if (wasLive.current === live) return;
    wasLive.current = live;
    const root = rootRef.current;
    const active = document.activeElement;
    if (!root || (active && active !== document.body && !root.contains(active))) return;
    (live ? muteRef : startRef).current?.focus();
  }, [live]);

  async function start() {
    setError(null);
    setNote(null);
    setRequesting(true);
    try {
      // Ask for the mic ourselves so a denial gets a clear message. The SDK opens its own stream.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
    } catch (err) {
      setRequesting(false);
      setError(micErrorText(err));
      return;
    }
    startSession({ agentId, connectionType: "webrtc" });
  }

  function toggleMute() {
    try {
      setMuted(!isMuted);
    } catch {
      // No active conversation (call just ended); the UI is about to return to idle.
    }
  }

  let dot = "bg-zinc-500";
  let line: string;
  if (live) {
    if (isMuted) {
      dot = "bg-red-500";
      line = "Mic muted — agent can't hear you";
    } else if (isSpeaking) {
      dot = "bg-sky-300";
      line = "Agent speaking…";
    } else {
      dot = "cs-live-dot bg-emerald-500";
      line = "Listening — describe the snow or ice and where it is";
    }
  } else if (connecting) {
    dot = "bg-amber-400";
    line = requesting && status !== "connecting" ? "Waiting for microphone permission…" : "Connecting…";
  } else if (error) {
    dot = "bg-red-500";
    line = error;
  } else {
    line = note ?? "Report a snow or ice problem by voice. Your report shows up on the map.";
  }
  const alarm = (live && isMuted) || (!live && !connecting && !!error);

  return (
    <div ref={rootRef} className="rounded-lg border border-line bg-surface-2/60 p-3">
      <p
        className={`mb-2 flex min-h-[2.5rem] items-start gap-2 text-xs leading-5 ${alarm ? "font-medium text-red-300" : "text-ink-2"}`}
        role="status"
        aria-live="polite"
      >
        <span className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
        <span>{line}</span>
      </p>

      {live ? (
        <div className="grid grid-cols-2 gap-2">
          <button
            ref={muteRef}
            type="button"
            onClick={toggleMute}
            aria-pressed={isMuted}
            className={`flex h-10 items-center justify-center gap-2 rounded-lg border text-sm font-medium transition-colors ${
              isMuted
                ? "border-red-500/50 bg-red-950/60 text-red-200 hover:bg-red-950"
                : "border-line bg-surface-2 text-ink hover:border-zinc-600 hover:bg-zinc-800"
            }`}
          >
            {/* Constant name + aria-pressed is the accessible toggle pattern; state shows in colour, icon and status line. */}
            {isMuted ? <MicOffIcon /> : <MicIcon />}
            Mute mic
          </button>
          <button
            type="button"
            onClick={() => endSession()}
            className="flex h-10 items-center justify-center gap-2 rounded-lg border border-line bg-surface-2 text-sm font-medium text-ink hover:border-red-500/50 hover:bg-red-950/40 hover:text-red-200"
          >
            <HangUpIcon />
            End call
          </button>
        </div>
      ) : (
        <button
          ref={startRef}
          type="button"
          onClick={() => !connecting && start()}
          aria-disabled={connecting}
          aria-busy={connecting}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-accent text-sm font-medium text-white transition-colors hover:bg-accent/85 aria-disabled:cursor-wait aria-disabled:opacity-70"
        >
          <MicIcon />
          {connecting ? "Connecting…" : "Talk to SnowTech 311"}
        </button>
      )}
    </div>
  );
}

const iconProps = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

function MicIcon() {
  return (
    <svg {...iconProps}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4" />
    </svg>
  );
}

function MicOffIcon() {
  return (
    <svg {...iconProps}>
      <path d="M2 2l20 20M15 9.34V5a3 3 0 0 0-5.68-1.33M9 9v2a3 3 0 0 0 5.12 2.12M19 10v1a7 7 0 0 1-1.07 3.7M5 10v1a7 7 0 0 0 11.08 5.69M12 18v4" />
    </svg>
  );
}

function HangUpIcon() {
  return (
    <svg {...iconProps}>
      <path d="M3 15.5c5-4.7 13-4.7 18 0l-2.2 2.2a1 1 0 0 1-1.3.1l-2.2-1.6a1 1 0 0 1-.4-.8V13a12 12 0 0 0-5.8 0v2.4a1 1 0 0 1-.4.8l-2.2 1.6a1 1 0 0 1-1.3-.1z" />
    </svg>
  );
}
