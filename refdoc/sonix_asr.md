# Real-time transcription
URL: /stt/rt/real-time-transcription

Learn about real-time transcription with low latency and high accuracy for all 60+ languages.

<HashRedirect from="termination-of-real-time-transcription-requests" to="/stt/rt/error-handling#request-termination" />

## Overview

Soniox Speech-to-Text AI lets you transcribe audio in real time with **low latency**
and **high accuracy** in over 60 languages. This is ideal for use cases like **live
captions, voice assistants, streaming analytics, and conversational AI.**

Real-time transcription is provided through our [WebSocket API](/stt/api-reference/websocket-api), which streams
results back to you as the audio is processed.

***

## How processing works

As audio is streamed into the API, Soniox returns a continuous stream of **tokens** — small units of text such as subwords, words, or spaces.

Each token carries a status flag (`is_final`) that tells you whether the token is **provisional** or **confirmed:**

* **Non-final token** (`is_final: false`) → Provisional text. Appears instantly but may change, disappear, or be replaced as more audio arrives.
* **Final token** (`is_final: true`) → Confirmed text. Once marked final, it will never change in future responses.

This means you get text right away (non-final for instant feedback), followed by the confirmed version (final for stable output).

<Callout type="warn">
  Non-final tokens may appear multiple times and change slightly until they stabilize into a final token. Final tokens are sent only once and never repeated.
</Callout>

### Example token evolution

Here’s how `"How are you doing?"` might arrive over time:

<Steps>
  <Step>
    **Initial guess (non-final):**

    ```json
    {"tokens": [{"text": "How",    "is_final": false},
                {"text": "'re",    "is_final": false}]}
    ```
  </Step>

  <Step>
    **Refined guess (non-final):**

    ```json
    {"tokens": [{"text": "How",    "is_final": false},
                {"text": " ",      "is_final": false},
                {"text": "are",    "is_final": false}]}
    ```
  </Step>

  <Step>
    **Mixed output (final + non-final):**

    ```json
    {"tokens": [{"text": "How",    "is_final": true},
                {"text": " ",      "is_final": true},
                {"text": "are",    "is_final": false},
                {"text": " ",      "is_final": false},
                {"text": "you",    "is_final": false}]}
    ```
  </Step>

  <Step>
    **Mixed output (final + non-final):**

    ```json
    {"tokens": [{"text": "are",    "is_final": true},
                {"text": " ",      "is_final": true},
                {"text": "you",    "is_final": true},
                {"text": " ",      "is_final": false},
                {"text": "do",     "is_final": false},
                {"text": "ing",    "is_final": false},
                {"text": "?",      "is_final": false}]}
    ```
  </Step>

  <Step>
    **Confirmed tokens (final):**

    ```json
    {"tokens": [{"text": " ",      "is_final": true},
                {"text": "do",     "is_final": true},
                {"text": "ing",    "is_final": true},
                {"text": "?",      "is_final": true}]}
    ```
  </Step>
</Steps>

**Bottom line:** The model may start with a shorthand guess like “How’re”, then
refine it into “How are you”, and finally extend it into “How are you doing?”.
Non-final tokens update instantly, while final tokens never change once
confirmed.

***

## Audio progress tracking

Each response also tells you **how much audio has been processed**:

* `audio_final_proc_ms` — audio processed into **final tokens.**
* `audio_total_proc_ms` — audio processed into **final + non-final tokens.**

Example:

```json
{
  "audio_final_proc_ms": 4800,
  "audio_total_proc_ms": 5250
}
```

**This means:**

* Audio up to **4.8s** has been processed and finalized (final tokens).
* Audio up to **5.25s** has been processed in total (final + non-final tokens).

***

## Getting final tokens sooner

There are two ways to obtain final tokens more quickly:

1. [Endpoint detection](/stt/rt/endpoint-detection) — the model can detect when a speaker has stopped talking and finalize tokens immediately.
2. [Manual finalization](/stt/rt/manual-finalization) — you can send a `"type": "finalize"` message over the WebSocket to force all pending tokens to finalize.

{/* **Example: Transcribe a live audio stream** */}

***

## Audio formats

Soniox supports both **auto-detected formats** (no configuration required) and **raw audio formats** (manual configuration required).

### Auto-detected formats

Soniox can automatically detect common container formats from stream headers.
No configuration needed — just set:

```json
{
  "audio_format": "auto"
}
```

Supported auto formats:

```text
aac, aiff, amr, asf, flac, mp3, ogg, wav, webm
```

### Raw audio formats

For raw audio streams without headers, you must provide:

* `audio_format` → encoding type.
* `sample_rate` →  sample rate in Hz.
* `num_channels` → number of channels (e.g. 1 (mono) or 2 (stereo)).

**Supported encodings:**

* PCM (signed): `pcm_s8`, `pcm_s16`, `pcm_s24`, `pcm_s32` (`le`/`be`).
* PCM (unsigned): `pcm_u8`, `pcm_u16`, `pcm_u24`, `pcm_u32` (`le`/`be`).
* Float PCM: `pcm_f32`, `pcm_f64` (`le`/`be`).
* Companded: `mulaw`, `alaw`.

**Example: raw PCM (16-bit, 16kHz, mono)**

```json
{
  "audio_format": "pcm_s16le",
  "sample_rate": 16000,
  "num_channels": 1
}
```

***

## Code example

**Prerequisite:** Complete the steps in [Get started](/stt/get-started).

<Tabs
  items={[
  'Python SDK',
  'Node SDK',
  'Python',
  'Node']}
>
  <Tab>
    <Accordions>
      <Accordion title="Code" id="code">
        See on GitHub: [soniox\_sdk\_realtime.py](https://github.com/soniox/soniox_examples/blob/master/speech_to_text/python_sdk/soniox_sdk_realtime.py).

        <FileCodeBlock path="./content/stt/rt/_examples/soniox_sdk_realtime.py" lang="python">
          ```
          import os
          import argparse
          from typing import Optional

          from soniox import SonioxClient
          from soniox.types import (
              RealtimeSTTConfig,
              StructuredContext,
              TranslationConfig,
              StructuredContextGeneralItem,
              StructuredContextTranslationTerm,
          )
          from soniox.utils import render_tokens, start_audio_thread, throttle_audio


          def get_config(audio_format: str, translation: Optional[str]) -> RealtimeSTTConfig:
              config = RealtimeSTTConfig(
                  # Select the model to use.
                  # See: soniox.com/docs/stt/models
                  model="stt-rt-v4",
                  #
                  # Set language hints when possible to significantly improve accuracy.
                  # See: soniox.com/docs/stt/concepts/language-hints
                  language_hints=["en", "es"],
                  #
                  # Enable language identification. Each token will include a "language" field.
                  # See: soniox.com/docs/stt/concepts/language-identification
                  enable_language_identification=True,
                  #
                  # Enable speaker diarization. Each token will include a "speaker" field.
                  # See: soniox.com/docs/stt/concepts/speaker-diarization
                  enable_speaker_diarization=True,
                  #
                  # Set context to help the model understand your domain, recognize important terms,
                  # and apply custom vocabulary and translation preferences.
                  # See: soniox.com/docs/stt/concepts/context
                  context=StructuredContext(
                      general=[
                          StructuredContextGeneralItem(key="domain", value="Healthcare"),
                          StructuredContextGeneralItem(
                              key="topic", value="Diabetes management consultation"
                          ),
                          StructuredContextGeneralItem(key="doctor", value="Dr. Martha Smith"),
                          StructuredContextGeneralItem(key="patient", value="Mr. David Miller"),
                          StructuredContextGeneralItem(
                              key="organization", value="St John's Hospital"
                          ),
                      ],
                      text="Mr. David Miller visited his healthcare provider last month for a routine follow-up related to diabetes care. The clinician reviewed his recent test results, noted improved glucose levels, and adjusted his medication schedule accordingly. They also discussed meal planning strategies and scheduled the next check-up for early spring.",
                      terms=[
                          "Celebrex",
                          "Zyrtec",
                          "Xanax",
                          "Prilosec",
                          "Amoxicillin Clavulanate Potassium",
                      ],
                      translation_terms=[
                          StructuredContextTranslationTerm(
                              source="Mr. Smith", target="Sr. Smith"
                          ),
                          StructuredContextTranslationTerm(
                              source="St John's", target="St John's"
                          ),
                          StructuredContextTranslationTerm(source="stroke", target="ictus"),
                      ],
                  ),
                  #
                  # Use endpointing to detect when the speaker stops.
                  # It finalizes all non-final tokens right away, minimizing latency.
                  # See: soniox.com/docs/stt/rt/endpoint-detection
                  enable_endpoint_detection=True,
              )

              # Audio format.
              # See: soniox.com/docs/stt/rt/real-time-transcription#audio-formats
              if audio_format == "auto":
                  # Set to "auto" to let Soniox detect the audio format automatically.
                  config.audio_format = "auto"
              elif audio_format == "pcm_s16le":
                  # Example of a raw audio format; Soniox supports many others as well.
                  config.audio_format = "pcm_s16le"
                  config.sample_rate = 16000
                  config.num_channels = 1
              else:
                  raise ValueError(f"Unsupported audio_format: {audio_format}")

              # Translation options.
              # See: soniox.com/docs/stt/rt/real-time-translation#translation-modes
              if translation == "none":
                  pass
              elif translation == "one_way":
                  # Translates all languages into the target language.
                  config.translation = TranslationConfig(
                      type="one_way",
                      target_language="es",
                  )
              elif translation == "two_way":
                  # Translates from language_a to language_b and back from language_b to language_a.
                  config.translation = TranslationConfig(
                      type="two_way",
                      language_a="en",
                      language_b="es",
                  )
              else:
                  raise ValueError(f"Unsupported translation: {translation}")

              return config


          def run_session(
              client: SonioxClient,
              audio_path: str,
              audio_format: str,
              translation: str,
          ) -> None:
              config = get_config(audio_format, translation)

              print("Connecting to Soniox...")
              with client.realtime.stt.connect(config=config) as session:
                  final_tokens = []

                  start_audio_thread(session, throttle_audio(audio_path, delay_seconds=0.1))
                  print("Session started.")

                  for event in session.receive_events():
                      # Error from server.
                      # See: https://soniox.com/docs/stt/api-reference/websocket-api#error-response
                      if event.error_code:
                          print(f"Error: {event.error_code} - {event.error_message}")

                      # Parse tokens from current response.
                      non_final_tokens = []
                      for token in event.tokens:
                          if token.is_final:
                              # Final tokens are returned once and should be appended to final_tokens.
                              final_tokens.append(token)
                          else:
                              # Non-final tokens update as more audio arrives; reset them on every response.
                              non_final_tokens.append(token)

                      # Render tokens.
                      print(render_tokens(final_tokens, non_final_tokens))

                      # Session finished.
                      if event.finished:
                          print("Session finished.")


          def main():
              parser = argparse.ArgumentParser()
              parser.add_argument("--audio_path", type=str)
              parser.add_argument("--audio_format", default="auto")
              parser.add_argument("--translation", default="none")
              args = parser.parse_args()

              api_key = os.environ.get("SONIOX_API_KEY")
              if api_key is None:
                  raise RuntimeError("Missing SONIOX_API_KEY.")

              client = SonioxClient()

              run_session(client, args.audio_path, args.audio_format, args.translation)


          if __name__ == "__main__":
              main()

          ```
        </FileCodeBlock>
      </Accordion>

      <Accordion title="Run" id="run">
        ```sh title="Terminal"
        # Transcribe a live audio stream
        python soniox_sdk_realtime.py --audio_path ../assets/coffee_shop.mp3

        # Transcribe a raw audio live stream
        python soniox_sdk_realtime.py --audio_path ../assets/coffee_shop.pcm_s16le --audio_format pcm_s16le
        ```
      </Accordion>
    </Accordions>
  </Tab>

  <Tab>
    <Accordions>
      <Accordion title="Code" id="code">
        See on GitHub: [soniox\_sdk\_realtime.js](https://github.com/soniox/soniox_examples/blob/master/speech_to_text/nodejs_sdk/soniox_sdk_realtime.js).

        <FileCodeBlock path="./content/stt/rt/_examples/soniox_sdk_realtime.js" lang="js">
          ```
          import { RealtimeUtteranceBuffer, SonioxNodeClient } from "@soniox/node";
          import fs from "fs";
          import { parseArgs } from "node:util";
          import process from "process";

          // Initialize the client.
          // The API key is read from the SONIOX_API_KEY environment variable.
          const client = new SonioxNodeClient();

          // Get session config based on CLI arguments.
          function getSessionConfig(audioFormat, translation) {
            const config = {
              // Select the model to use.
              // See: soniox.com/docs/stt/models
              model: "stt-rt-v4",

              // Set language hints when possible to significantly improve accuracy.
              // See: soniox.com/docs/stt/concepts/language-hints
              language_hints: ["en", "es"],

              // Enable language identification. Each token will include a "language" field.
              // See: soniox.com/docs/stt/concepts/language-identification
              enable_language_identification: true,

              // Enable speaker diarization. Each token will include a "speaker" field.
              // See: soniox.com/docs/stt/concepts/speaker-diarization
              enable_speaker_diarization: true,

              // Set context to help the model understand your domain, recognize important terms,
              // and apply custom vocabulary and translation preferences.
              // See: soniox.com/docs/stt/concepts/context
              context: {
                general: [
                  { key: "domain", value: "Healthcare" },
                  { key: "topic", value: "Diabetes management consultation" },
                  { key: "doctor", value: "Dr. Martha Smith" },
                  { key: "patient", value: "Mr. David Miller" },
                  { key: "organization", value: "St John's Hospital" },
                ],
                text: "Mr. David Miller visited his healthcare provider last month for a routine follow-up related to diabetes care. The clinician reviewed his recent test results, noted improved glucose levels, and adjusted his medication schedule accordingly. They also discussed meal planning strategies and scheduled the next check-up for early spring.",
                terms: [
                  "Celebrex",
                  "Zyrtec",
                  "Xanax",
                  "Prilosec",
                  "Amoxicillin Clavulanate Potassium",
                ],
                translation_terms: [
                  { source: "Mr. Smith", target: "Sr. Smith" },
                  { source: "St John's", target: "St John's" },
                  { source: "stroke", target: "ictus" },
                ],
              },

              // Use endpointing to detect when the speaker stops.
              // It finalizes all non-final tokens right away, minimizing latency.
              // See: soniox.com/docs/stt/rt/endpoint-detection
              enable_endpoint_detection: true,
            };

            // Audio format.
            // See: soniox.com/docs/stt/rt/real-time-transcription#audio-formats
            if (audioFormat === "auto") {
              config.audio_format = "auto";
            } else if (audioFormat === "pcm_s16le") {
              config.audio_format = "pcm_s16le";
              config.sample_rate = 16000;
              config.num_channels = 1;
            } else {
              throw new Error(`Unsupported audio_format: ${audioFormat}`);
            }

            // Translation options.
            // See: soniox.com/docs/stt/rt/real-time-translation#translation-modes
            if (translation === "one_way") {
              config.translation = { type: "one_way", target_language: "es" };
            } else if (translation === "two_way") {
              config.translation = {
                type: "two_way",
                language_a: "en",
                language_b: "es",
              };
            } else if (translation !== "none") {
              throw new Error(`Unsupported translation: ${translation}`);
            }

            return config;
          }

          // Render a single utterance as readable text.
          function renderUtterance(utterance) {
            return utterance.segments
              .map((segment) => {
                const speaker = segment.speaker ? `Speaker ${segment.speaker}:` : "";
                const isTranslation =
                  segment.tokens[0]?.translation_status === "translation";
                const lang = segment.language
                  ? `${isTranslation ? "[Translation] " : ""}[${segment.language}]`
                  : "";
                return `${speaker} ${lang} ${segment.text.trimStart()}`;
              })
              .join("\n");
          }

          async function runSession(audioPath, audioFormat, translation) {
            const config = getSessionConfig(audioFormat, translation);

            // Create a real-time STT session.
            const session = client.realtime.stt(config);

            // Utterance buffer collects tokens and flushes complete utterances on endpoints.
            const buffer = new RealtimeUtteranceBuffer();

            // Feed every result into the buffer.
            session.on("result", (result) => {
              buffer.addResult(result);
            });

            // When an endpoint is detected, flush the buffer into a complete utterance.
            session.on("endpoint", () => {
              const utterance = buffer.markEndpoint();
              if (utterance) {
                console.log(renderUtterance(utterance));
              }
            });

            session.on("finished", () => {
              // Flush any remaining tokens after the session ends.
              const utterance = buffer.markEndpoint();
              if (utterance) {
                console.log(renderUtterance(utterance));
              }
              console.log("Session finished.");
            });

            session.on("error", (err) => {
              console.error("Session error:", err);
            });

            // Connect to the Soniox realtime API.
            console.log("Connecting to Soniox...");
            await session.connect();
            console.log("Session started.");

            // Stream the audio file and finish when done.
            await session.sendStream(
              fs.createReadStream(audioPath, { highWaterMark: 3840 }),
              { pace_ms: 120, finish: true },
            );
          }

          async function main() {
            const { values: argv } = parseArgs({
              options: {
                audio_path: { type: "string" },
                audio_format: { type: "string", default: "auto" },
                translation: { type: "string", default: "none" },
              },
            });

            if (!argv.audio_path) {
              throw new Error("Missing --audio_path argument.");
            }

            await runSession(argv.audio_path, argv.audio_format, argv.translation);
          }

          main().catch((err) => {
            console.error("Error:", err.message);
            process.exit(1);
          });

          ```
        </FileCodeBlock>
      </Accordion>

      <Accordion title="Run" id="run">
        ```sh title="Terminal"
        # Transcribe a live audio stream
        node soniox_sdk_realtime.js --audio_path ../assets/coffee_shop.mp3

        # Transcribe a raw audio live stream
        node soniox_sdk_realtime.js --audio_path ../assets/coffee_shop.pcm_s16le --audio_format pcm_s16le
        ```
      </Accordion>
    </Accordions>

    {/* NOTE: Empty tag is needed so code block renders correctly */}

    <div />
  </Tab>

  <Tab>
    <Accordions>
      <Accordion title="Code" id="code">
        See on GitHub: [soniox\_realtime.py](https://github.com/soniox/soniox_examples/blob/master/speech_to_text/python/soniox_realtime.py).

        <FileCodeBlock path="./content/stt/rt/_examples/soniox_realtime.py" lang="python">
          ```
          import json
          import os
          import threading
          import time
          import argparse
          from typing import Optional

          from websockets import ConnectionClosedOK
          from websockets.sync.client import connect

          SONIOX_WEBSOCKET_URL = "wss://stt-rt.soniox.com/transcribe-websocket"


          # Get Soniox STT config.
          def get_config(api_key: str, audio_format: str, translation: str) -> dict:
              config = {
                  # Get your API key at console.soniox.com, then run: export SONIOX_API_KEY=<YOUR_API_KEY>
                  "api_key": api_key,
                  #
                  # Select the model to use.
                  # See: soniox.com/docs/stt/models
                  "model": "stt-rt-v4",
                  #
                  # Set language hints when possible to significantly improve accuracy.
                  # See: soniox.com/docs/stt/concepts/language-hints
                  "language_hints": ["en", "es"],
                  #
                  # Enable language identification. Each token will include a "language" field.
                  # See: soniox.com/docs/stt/concepts/language-identification
                  "enable_language_identification": True,
                  #
                  # Enable speaker diarization. Each token will include a "speaker" field.
                  # See: soniox.com/docs/stt/concepts/speaker-diarization
                  "enable_speaker_diarization": True,
                  #
                  # Set context to help the model understand your domain, recognize important terms,
                  # and apply custom vocabulary and translation preferences.
                  # See: soniox.com/docs/stt/concepts/context
                  "context": {
                      "general": [
                          {"key": "domain", "value": "Healthcare"},
                          {"key": "topic", "value": "Diabetes management consultation"},
                          {"key": "doctor", "value": "Dr. Martha Smith"},
                          {"key": "patient", "value": "Mr. David Miller"},
                          {"key": "organization", "value": "St John's Hospital"},
                      ],
                      "text": "Mr. David Miller visited his healthcare provider last month for a routine follow-up related to diabetes care. The clinician reviewed his recent test results, noted improved glucose levels, and adjusted his medication schedule accordingly. They also discussed meal planning strategies and scheduled the next check-up for early spring.",
                      "terms": [
                          "Celebrex",
                          "Zyrtec",
                          "Xanax",
                          "Prilosec",
                          "Amoxicillin Clavulanate Potassium",
                      ],
                      "translation_terms": [
                          {"source": "Mr. Smith", "target": "Sr. Smith"},
                          {"source": "St John's", "target": "St John's"},
                          {"source": "stroke", "target": "ictus"},
                      ],
                  },
                  #
                  # Use endpointing to detect when the speaker stops.
                  # It finalizes all non-final tokens right away, minimizing latency.
                  # See: soniox.com/docs/stt/rt/endpoint-detection
                  "enable_endpoint_detection": True,
              }

              # Audio format.
              # See: soniox.com/docs/stt/rt/real-time-transcription#audio-formats
              if audio_format == "auto":
                  # Set to "auto" to let Soniox detect the audio format automatically.
                  config["audio_format"] = "auto"
              elif audio_format == "pcm_s16le":
                  # Example of a raw audio format; Soniox supports many others as well.
                  config["audio_format"] = "pcm_s16le"
                  config["sample_rate"] = 16000
                  config["num_channels"] = 1
              else:
                  raise ValueError(f"Unsupported audio_format: {audio_format}")

              # Translation options.
              # See: soniox.com/docs/stt/rt/real-time-translation#translation-modes
              if translation == "none":
                  pass
              elif translation == "one_way":
                  # Translates all languages into the target language.
                  config["translation"] = {
                      "type": "one_way",
                      "target_language": "es",
                  }
              elif translation == "two_way":
                  # Translates from language_a to language_b and back from language_b to language_a.
                  config["translation"] = {
                      "type": "two_way",
                      "language_a": "en",
                      "language_b": "es",
                  }
              else:
                  raise ValueError(f"Unsupported translation: {translation}")

              return config


          # Read the audio file and send its bytes to the websocket.
          def stream_audio(audio_path: str, ws) -> None:
              with open(audio_path, "rb") as fh:
                  while True:
                      data = fh.read(3840)
                      if len(data) == 0:
                          break
                      ws.send(data)
                      # Sleep for 120 ms to simulate real-time streaming.
                      time.sleep(0.120)

              # Empty string signals end-of-audio to the server
              ws.send("")


          # Convert tokens into a readable transcript.
          def render_tokens(final_tokens: list[dict], non_final_tokens: list[dict]) -> str:
              text_parts: list[str] = []
              current_speaker: Optional[str] = None
              current_language: Optional[str] = None

              # Process all tokens in order.
              for token in final_tokens + non_final_tokens:
                  text = token["text"]
                  speaker = token.get("speaker")
                  language = token.get("language")
                  is_translation = token.get("translation_status") == "translation"

                  # Speaker changed -> add a speaker tag.
                  if speaker is not None and speaker != current_speaker:
                      if current_speaker is not None:
                          text_parts.append("\n\n")
                      current_speaker = speaker
                      current_language = None  # Reset language on speaker changes.
                      text_parts.append(f"Speaker {current_speaker}:")

                  # Language changed -> add a language or translation tag.
                  if language is not None and language != current_language:
                      current_language = language
                      prefix = "[Translation] " if is_translation else ""
                      text_parts.append(f"\n{prefix}[{current_language}] ")
                      text = text.lstrip()

                  text_parts.append(text)

              text_parts.append("\n===============================")

              return "".join(text_parts)


          def run_session(
              api_key: str,
              audio_path: str,
              audio_format: str,
              translation: str,
          ) -> None:
              config = get_config(api_key, audio_format, translation)

              print("Connecting to Soniox...")
              with connect(SONIOX_WEBSOCKET_URL) as ws:
                  # Send first request with config.
                  ws.send(json.dumps(config))

                  # Start streaming audio in the background.
                  threading.Thread(
                      target=stream_audio,
                      args=(audio_path, ws),
                      daemon=True,
                  ).start()

                  print("Session started.")

                  final_tokens: list[dict] = []

                  try:
                      while True:
                          message = ws.recv()
                          res = json.loads(message)

                          # Error from server.
                          # See: https://soniox.com/docs/stt/api-reference/websocket-api#error-response
                          if res.get("error_code") is not None:
                              print(f"Error: {res['error_code']} - {res['error_message']}")
                              break

                          # Parse tokens from current response.
                          non_final_tokens: list[dict] = []
                          for token in res.get("tokens", []):
                              if token.get("text"):
                                  if token.get("is_final"):
                                      # Final tokens are returned once and should be appended to final_tokens.
                                      final_tokens.append(token)
                                  else:
                                      # Non-final tokens update as more audio arrives; reset them on every response.
                                      non_final_tokens.append(token)

                          # Render tokens.
                          text = render_tokens(final_tokens, non_final_tokens)
                          print(text)

                          # Session finished.
                          if res.get("finished"):
                              print("Session finished.")

                  except ConnectionClosedOK:
                      # Normal, server closed after finished.
                      pass
                  except KeyboardInterrupt:
                      print("\nInterrupted by user.")
                  except Exception as e:
                      print(f"Error: {e}")


          def main():
              parser = argparse.ArgumentParser()
              parser.add_argument("--audio_path", type=str)
              parser.add_argument("--audio_format", default="auto")
              parser.add_argument("--translation", default="none")
              args = parser.parse_args()

              api_key = os.environ.get("SONIOX_API_KEY")
              if api_key is None:
                  raise RuntimeError("Missing SONIOX_API_KEY.")

              run_session(api_key, args.audio_path, args.audio_format, args.translation)


          if __name__ == "__main__":
              main()

          ```
        </FileCodeBlock>
      </Accordion>

      <Accordion title="Run" id="run">
        ```sh title="Terminal"
        # Transcribe a live audio stream
        python soniox_realtime.py --audio_path ../assets/coffee_shop.mp3

        # Transcribe a raw audio live stream
        python soniox_realtime.py --audio_path ../assets/coffee_shop.pcm_s16le --audio_format pcm_s16le
        ```
      </Accordion>
    </Accordions>
  </Tab>

  <Tab>
    <Accordions>
      <Accordion title="Code" id="code">
        See on GitHub: [soniox\_realtime.js](https://github.com/soniox/soniox_examples/blob/master/speech_to_text/nodejs/soniox_realtime.js).

        <FileCodeBlock path="./content/stt/rt/_examples/soniox_realtime.js" lang="js">
          ```
          import fs from "fs";
          import WebSocket from "ws";
          import { parseArgs } from "node:util";

          const SONIOX_WEBSOCKET_URL = "wss://stt-rt.soniox.com/transcribe-websocket";

          // Get Soniox STT config
          function getConfig(apiKey, audioFormat, translation) {
            const config = {
              // Get your API key at console.soniox.com, then run: export SONIOX_API_KEY=<YOUR_API_KEY>
              api_key: apiKey,

              // Select the model to use.
              // See: soniox.com/docs/stt/models
              model: "stt-rt-v4",

              // Set language hints when possible to significantly improve accuracy.
              // See: soniox.com/docs/stt/concepts/language-hints
              language_hints: ["en", "es"],

              // Enable language identification. Each token will include a "language" field.
              // See: soniox.com/docs/stt/concepts/language-identification
              enable_language_identification: true,

              // Enable speaker diarization. Each token will include a "speaker" field.
              // See: soniox.com/docs/stt/concepts/speaker-diarization
              enable_speaker_diarization: true,

              // Set context to help the model understand your domain, recognize important terms,
              // and apply custom vocabulary and translation preferences.
              // See: soniox.com/docs/stt/concepts/context
              context: {
                general: [
                  { key: "domain", value: "Healthcare" },
                  { key: "topic", value: "Diabetes management consultation" },
                  { key: "doctor", value: "Dr. Martha Smith" },
                  { key: "patient", value: "Mr. David Miller" },
                  { key: "organization", value: "St John's Hospital" },
                ],
                text: "Mr. David Miller visited his healthcare provider last month for a routine follow-up related to diabetes care. The clinician reviewed his recent test results, noted improved glucose levels, and adjusted his medication schedule accordingly. They also discussed meal planning strategies and scheduled the next check-up for early spring.",
                terms: [
                  "Celebrex",
                  "Zyrtec",
                  "Xanax",
                  "Prilosec",
                  "Amoxicillin Clavulanate Potassium",
                ],
                translation_terms: [
                  { source: "Mr. Smith", target: "Sr. Smith" },
                  { source: "St John's", target: "St John's" },
                  { source: "stroke", target: "ictus" },
                ],
              },

              // Use endpointing to detect when the speaker stops.
              // It finalizes all non-final tokens right away, minimizing latency.
              // See: soniox.com/docs/stt/rt/endpoint-detection
              enable_endpoint_detection: true,
            };

            // Audio format.
            // See: soniox.com/docs/stt/rt/real-time-transcription#audio-formats
            if (audioFormat === "auto") {
              // Set to "auto" to let Soniox detect the audio format automatically.
              config.audio_format = "auto";
            } else if (audioFormat === "pcm_s16le") {
              // Example of a raw audio format; Soniox supports many others as well.
              config.audio_format = "pcm_s16le";
              config.sample_rate = 16000;
              config.num_channels = 1;
            } else {
              throw new Error(`Unsupported audio_format: ${audioFormat}`);
            }

            // Translation options.
            // See: soniox.com/docs/stt/rt/real-time-translation#translation-modes
            if (translation === "one_way") {
              // Translates all languages into the target language.
              config.translation = { type: "one_way", target_language: "es" };
            } else if (translation === "two_way") {
              // Translates from language_a to language_b and back from language_b to language_a.
              config.translation = {
                type: "two_way",
                language_a: "en",
                language_b: "es",
              };
            } else if (translation !== "none") {
              throw new Error(`Unsupported translation: ${translation}`);
            }

            return config;
          }

          // Read the audio file and send its bytes to the websocket.
          async function streamAudio(audioPath, ws) {
            const stream = fs.createReadStream(audioPath, { highWaterMark: 3840 });

            for await (const chunk of stream) {
              ws.send(chunk);
              // Sleep for 120 ms to simulate real-time streaming.
              await new Promise((res) => setTimeout(res, 120));
            }

            // Empty string signals end-of-audio to the server
            ws.send("");
          }

          // Convert tokens into readable transcript
          function renderTokens(finalTokens, nonFinalTokens) {
            let textParts = [];
            let currentSpeaker = null;
            let currentLanguage = null;

            const allTokens = [...finalTokens, ...nonFinalTokens];

            // Process all tokens in order.
            for (const token of allTokens) {
              let { text, speaker, language } = token;
              const isTranslation = token.translation_status === "translation";

              // Speaker changed -> add a speaker tag.
              if (speaker && speaker !== currentSpeaker) {
                if (currentSpeaker !== null) textParts.push("\n\n");
                currentSpeaker = speaker;
                currentLanguage = null; // Reset language on speaker changes.
                textParts.push(`Speaker ${currentSpeaker}:`);
              }

              // Language changed -> add a language or translation tag.
              if (language && language !== currentLanguage) {
                currentLanguage = language;
                const prefix = isTranslation ? "[Translation] " : "";
                textParts.push(`\n${prefix}[${currentLanguage}] `);
                text = text.trimStart();
              }

              textParts.push(text);
            }

            textParts.push("\n===============================");
            return textParts.join("");
          }

          function runSession(apiKey, audioPath, audioFormat, translation) {
            const config = getConfig(apiKey, audioFormat, translation);

            console.log("Connecting to Soniox...");
            const ws = new WebSocket(SONIOX_WEBSOCKET_URL);

            let finalTokens = [];

            ws.on("open", () => {
              // Send first request with config.
              ws.send(JSON.stringify(config));

              // Start streaming audio in the background.
              streamAudio(audioPath, ws).catch((err) =>
                console.error("Audio stream error:", err),
              );
              console.log("Session started.");
            });

            ws.on("message", (msg) => {
              const res = JSON.parse(msg.toString());

              // Error from server.
              // See: https://soniox.com/docs/stt/api-reference/websocket-api#error-response
              if (res.error_code) {
                console.error(`Error: ${res.error_code} - ${res.error_message}`);
                ws.close();
                return;
              }

              // Parse tokens from current response.
              let nonFinalTokens = [];
              if (res.tokens) {
                for (const token of res.tokens) {
                  if (token.text) {
                    if (token.is_final) {
                      // Final tokens are returned once and should be appended to final_tokens.
                      finalTokens.push(token);
                    } else {
                      // Non-final tokens update as more audio arrives; reset them on every response.
                      nonFinalTokens.push(token);
                    }
                  }
                }
              }

              // Render tokens.
              const text = renderTokens(finalTokens, nonFinalTokens);
              console.log(text);

              // Session finished.
              if (res.finished) {
                console.log("Session finished.");
                ws.close();
              }
            });

            ws.on("error", (err) => console.error("WebSocket error:", err));
          }

          async function main() {
            const { values: argv } = parseArgs({
              options: {
                audio_path: { type: "string", required: true },
                audio_format: { type: "string", default: "auto" },
                translation: { type: "string", default: "none" },
              },
            });

            const apiKey = process.env.SONIOX_API_KEY;
            if (!apiKey) {
              throw new Error(
                "Missing SONIOX_API_KEY.\n" +
                  "1. Get your API key at https://console.soniox.com\n" +
                  "2. Run: export SONIOX_API_KEY=<YOUR_API_KEY>",
              );
            }

            runSession(apiKey, argv.audio_path, argv.audio_format, argv.translation);
          }

          main().catch((err) => {
            console.error("Error:", err.message);
            process.exit(1);
          });

          ```
        </FileCodeBlock>
      </Accordion>

      <Accordion title="Run" id="run">
        ```sh title="Terminal"
        # Transcribe a live audio stream
        node soniox_realtime.js --audio_path ../assets/coffee_shop.mp3

        # Transcribe a raw audio live stream
        node soniox_realtime.js --audio_path ../assets/coffee_shop.pcm_s16le --audio_format pcm_s16le
        ```
      </Accordion>
    </Accordions>
  </Tab>
</Tabs>
