
const API_URL = "/voice/assistant";
let accessToken = null;

// Login elements
const loginForm = document.getElementById("loginForm");
const loginButton = document.getElementById("loginButton");
const logoutButton = document.getElementById("logoutButton");
const authStatus = document.getElementById("authStatus");

// Voice-agent elements
const startButton = document.getElementById("startRecording");
const stopButton = document.getElementById("stopRecording");
const textForm = document.getElementById("textForm");
const sendTextButton = document.getElementById("sendText");

// Response elements
const statusElement = document.getElementById("status");
const transcriptElement = document.getElementById("transcript");
const answerElement = document.getElementById("answer");
const audioPlayer = document.getElementById("audioPlayer");

// Recording state
let mediaRecorder = null;
let microphoneStream = null;
let audioChunks = [];
let recordingMimeType = "";
let audioObjectUrl = null;


// --------------------------------------------------
// Login
// --------------------------------------------------

loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    loginButton.disabled = true;
    authStatus.textContent = "Signing in…";

    try {
        const response = await fetch("/auth/login", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                email: document.getElementById("loginEmail").value.trim(),
                password: document.getElementById("loginPassword").value
            })
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail || "Sign-in failed.");
        }

        accessToken = result.access_token;

        document.getElementById("loginPassword").value = "";

        authStatus.textContent =
            `Signed in as ${result.role}. Token expires in ${Math.floor(result.expires_in / 60)} minutes.`;

        logoutButton.hidden = false;
        loginButton.hidden = true;

        setStatus("Signed in. You can now ask about your account and orders.");

    } catch (error) {
        accessToken = null;
        authStatus.textContent = error.message || "Sign-in failed.";

    } finally {
        loginButton.disabled = false;
    }
});


// --------------------------------------------------
// Logout
// --------------------------------------------------

logoutButton.addEventListener("click", () => {
    accessToken = null;

    loginForm.reset();

    loginButton.hidden = false;
    logoutButton.hidden = true;

    authStatus.textContent = "Not signed in.";

    setStatus("Signed out.");
});


// --------------------------------------------------
// Status and settings
// --------------------------------------------------

function setStatus(message) {
    statusElement.textContent = message;
}

function getSettings() {
    const sessionId =
        document.getElementById("sessionId").value.trim();

    if (!accessToken) {
        throw new Error("Sign in before sending a request.");
    }

    if (!sessionId) {
        throw new Error("Enter a session ID.");
    }

    return {
        sessionId,

        enableTranscription:
            document.getElementById("enableTranscription").checked,

        enableSpeech:
            document.getElementById("enableSpeech").checked,

        voice:
            document.getElementById("voice").value
    };
}

function setBusy(busy) {
    startButton.disabled = busy;
    sendTextButton.disabled = busy;
}


// --------------------------------------------------
// Audio recording format
// --------------------------------------------------

function getRecordingFormat() {
    const formats = [
        {
            mime: "audio/webm;codecs=opus",
            extension: "webm"
        },
        {
            mime: "audio/webm",
            extension: "webm"
        },
        {
            mime: "audio/mp4",
            extension: "m4a"
        }
    ];

    for (const format of formats) {
        if (
            typeof MediaRecorder !== "undefined" &&
            MediaRecorder.isTypeSupported(format.mime)
        ) {
            return format;
        }
    }

    return null;
}


// --------------------------------------------------
// Start microphone recording
// --------------------------------------------------

async function startRecording() {
    try {
        const settings = getSettings();

        if (!settings.enableTranscription) {
            throw new Error(
                "Enable the transcription checkbox to use microphone input."
            );
        }

        if (
            !navigator.mediaDevices?.getUserMedia ||
            typeof MediaRecorder === "undefined"
        ) {
            throw new Error(
                "Your browser does not support microphone recording. " +
                "Use a recent browser over localhost or HTTPS."
            );
        }

        const format = getRecordingFormat();

        if (!format) {
            throw new Error(
                "This browser does not support the configured audio formats."
            );
        }

        microphoneStream =
            await navigator.mediaDevices.getUserMedia({
                audio: true
            });

        audioChunks = [];
        recordingMimeType = format.mime;

        mediaRecorder = new MediaRecorder(microphoneStream, {
            mimeType: format.mime
        });

        mediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };

        mediaRecorder.onstop = async () => {
            microphoneStream?.getTracks().forEach(
                (track) => track.stop()
            );

            microphoneStream = null;

            const blob = new Blob(audioChunks, {
                type: recordingMimeType
            });

            if (blob.size === 0) {
                setStatus("No audio was recorded. Try again.");
                startButton.disabled = false;
                stopButton.disabled = true;
                return;
            }

            await sendAudio(blob, format.extension);
        };

        mediaRecorder.start();

        startButton.disabled = true;
        stopButton.disabled = false;

        setStatus("Recording… Speak now.");

    } catch (error) {
        microphoneStream?.getTracks().forEach(
            (track) => track.stop()
        );

        microphoneStream = null;

        setStatus(error.message || "Could not start recording.");
    }
}


// --------------------------------------------------
// Stop microphone recording
// --------------------------------------------------

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        stopButton.disabled = true;

        setStatus("Preparing your recording…");

        mediaRecorder.stop();
    }
}


// --------------------------------------------------
// Send request to the voice assistant
// --------------------------------------------------

async function sendToAgent(formData) {
    setBusy(true);
    startButton.disabled = true;
    stopButton.disabled = true;

    setStatus("Processing your request…");

    try {
        const response = await fetch(API_URL, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${accessToken}`
            },
            body: formData
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.detail ||
                result.message ||
                "The request failed."
            );
        }

        transcriptElement.textContent =
            result.transcript || "No speech transcript (text input).";

        answerElement.textContent =
            result.response_text || "The agent returned no answer.";

        // Release the previous audio resource.
        if (audioObjectUrl) {
            URL.revokeObjectURL(audioObjectUrl);
            audioObjectUrl = null;
        }

        audioPlayer.pause();
        audioPlayer.removeAttribute("src");
        audioPlayer.load();

        // Decode and play the generated speech.
        if (result.audio_base64) {
            const binary = atob(result.audio_base64);
            const bytes = new Uint8Array(binary.length);

            for (let i = 0; i < binary.length; i++) {
                bytes[i] = binary.charCodeAt(i);
            }

            const audioBlob = new Blob([bytes], {
                type: result.audio_content_type || "audio/mpeg"
            });

            audioObjectUrl = URL.createObjectURL(audioBlob);

            audioPlayer.src = audioObjectUrl;
            audioPlayer.load();

            try {
                await audioPlayer.play();

                setStatus(
                    "Response ready — playing voice answer."
                );

            } catch {
                setStatus(
                    "Response ready. Press Play to hear the voice answer."
                );
            }

        } else {
            setStatus("Response ready.");
        }

    } catch (error) {
        setStatus(error.message || "Something went wrong.");

    } finally {
        setBusy(false);
        startButton.disabled = false;
        stopButton.disabled = true;
    }
}


// --------------------------------------------------
// Submit microphone audio
// --------------------------------------------------

async function sendAudio(blob, extension) {
    try {
        const settings = getSettings();

        if (!settings.enableTranscription) {
            throw new Error(
                "Enable transcription to submit microphone audio."
            );
        }

        const formData = new FormData();

        formData.append(
            "audio",
            blob,
            `recording.${extension}`
        );

        formData.append("session_id", settings.sessionId);
        formData.append("enable_transcription", "true");
        formData.append(
            "enable_speech",
            String(settings.enableSpeech)
        );

        formData.append("voice", settings.voice);
        formData.append("language", "en");

        await sendToAgent(formData);

    } catch (error) {
        setStatus(error.message || "Could not submit audio.");

        startButton.disabled = false;
        stopButton.disabled = true;
    }
}


// --------------------------------------------------
// Submit text message
// --------------------------------------------------

textForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    try {
        const settings = getSettings();

        const message =
            document.getElementById("message").value.trim();

        if (!message) {
            throw new Error("Enter a question first.");
        }

        if (message.length > 4000) {
            throw new Error(
                "Your message must be 4,000 characters or fewer."
            );
        }

        const formData = new FormData();

        formData.append("message", message);
        formData.append("session_id", settings.sessionId);

        // Transcription is unnecessary for typed input.
        formData.append("enable_transcription", "false");

        formData.append(
            "enable_speech",
            String(settings.enableSpeech)
        );

        formData.append("voice", settings.voice);
        formData.append("language", "en");

        await sendToAgent(formData);

    } catch (error) {
        setStatus(error.message || "Could not send message.");
    }
});


// --------------------------------------------------
// Register recording controls
// --------------------------------------------------

startButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", stopRecording);
