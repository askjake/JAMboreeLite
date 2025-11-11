#include <Wire.h>

/* ===================== Config / pins ===================== */
constexpr byte I2C_SLAVE_ADDR = 0x34; // 0x34 (52 dec)
constexpr int  RESET_PIN      = A7;    // Reset line for all remotes
const int remotePins[16] = {12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 13, A0, A1, A2, A3};

/* ===================== Protocol / state ===================== */
volatile bool ackReceived = false;          // true when master ACKs (cmd 0x02)
unsigned long ackTimeout = 300;             // ms
byte retriesPerCmd = 10;                    // resend attempts per command on timeout

byte CFG_REG = 0xAF;
byte INT_REG = 0x01;
byte EVT_REG = 0x01;
byte BLANK   = 0x00;

volatile byte  KEY_CMD = 0;                 // last key set by trigger

volatile boolean clearInterruptFlag = false;
volatile boolean initFlag           = true;
bool     debugOn                    = false;

/* ===================== Event FIFO (DOWN/UP) ===================== */
#define EVENT_QUEUE_SIZE 2048
#define EVENT_QUEUE_MASK (EVENT_QUEUE_SIZE - 1)
volatile byte     eventQ[EVENT_QUEUE_SIZE];
volatile uint16_t eventHead = 0, eventTail = 0;

static inline bool eventEmpty() { return eventHead == eventTail; }
static inline bool eventFull()  { return ((eventHead + 1) & EVENT_QUEUE_MASK) == eventTail; }
static inline void eventEnq_isrSafe(byte v) {
  uint16_t next = (eventHead + 1) & EVENT_QUEUE_MASK;
  if (next != eventTail) { eventQ[eventHead] = v; eventHead = next; }
}
static inline bool eventDeq_isrSafe(byte &out) {
  if (eventEmpty()) return false;
  out = eventQ[eventTail];
  eventTail = (eventTail + 1) & EVENT_QUEUE_MASK;
  return true;
}

/* ===================== Per-command TX gating ===================== */
volatile byte  waitForCmd   = 0;
volatile bool  txSeenForCmd = false;

/* ===================== I2C TX/RX ring logs with timestamps ===================== */
#define TXLOG_CAP 16
#define RXLOG_CAP 16
volatile byte     txLog[TXLOG_CAP][16];
volatile byte     txLogLen[TXLOG_CAP];
volatile uint32_t txLogTs[TXLOG_CAP];
volatile uint8_t  txLogHead = 0, txLogTail = 0;

volatile byte     rxLog[RXLOG_CAP][64];
volatile byte     rxLogLen[RXLOG_CAP];
volatile uint32_t rxLogTs[RXLOG_CAP];
volatile uint8_t  rxLogHead = 0, rxLogTail = 0;

static inline bool txLogEmpty() { return txLogHead == txLogTail; }
static inline void txLogPush(const byte* data, byte len, uint32_t ts) {
  uint8_t next = (uint8_t)(txLogHead + 1) % TXLOG_CAP;
  if (next == txLogTail) { txLogTail = (uint8_t)(txLogTail + 1) % TXLOG_CAP; }
  if (len > 16) len = 16;
  for (byte i=0;i<len;i++) txLog[txLogHead][i] = data[i];
  txLogLen[txLogHead] = len;
  txLogTs[txLogHead]  = ts;
  txLogHead = next;
}
static inline bool txLogPop(byte* out, byte& len, uint32_t& ts) {
  if (txLogEmpty()) return false;
  len = txLogLen[txLogTail];
  ts  = txLogTs[txLogTail];
  for (byte i=0;i<len;i++) out[i] = txLog[txLogTail][i];
  txLogTail = (uint8_t)(txLogTail + 1) % TXLOG_CAP;
  return true;
}

static inline bool rxLogEmpty() { return rxLogHead == rxLogTail; }
static inline void rxLogPush(const byte* data, byte len, uint32_t ts) {
  uint8_t next = (uint8_t)(rxLogHead + 1) % RXLOG_CAP;
  if (next == rxLogTail) { rxLogTail = (uint8_t)(rxLogTail + 1) % RXLOG_CAP; }
  if (len > 64) len = 64;
  for (byte i=0;i<len;i++) rxLog[rxLogHead][i] = data[i];
  rxLogLen[rxLogHead] = len;
  rxLogTs[rxLogHead]  = ts;
  rxLogHead = next;
}
static inline bool rxLogPop(byte* out, byte& len, uint32_t& ts) {
  if (rxLogEmpty()) return false;
  len = rxLogLen[rxLogTail];
  ts  = rxLogTs[rxLogTail];
  for (byte i=0;i<len;i++) out[i] = rxLog[rxLogTail][i];
  rxLogTail = (uint8_t)(rxLogTail + 1) % RXLOG_CAP;
  return true;
}

/* ===================== Button map (buttonNum -> hex down/up) ===================== */
const char* buttonActions[40][2] = {
  {"81", "01"}, {"8C", "0C"}, {"8B", "0B"}, {"83", "03"}, {"95", "15"}, {"96", "16"},
  {"97", "17"}, {"98", "18"}, {"99", "19"}, {"9A", "1A"}, {"A2", "22"}, {"A3", "23"},
  {"A4", "24"}, {"9F", "1F"}, {"A0", "20"}, {"A1", "21"}, {"A9", "29"}, {"AA", "2A"},
  {"AB", "2B"}, {"AC", "2C"}, {"AD", "2D"}, {"AE", "2E"}, {"B6", "36"}, {"B7", "37"},
  {"B8", "38"}, {"B3", "33"}, {"B4", "34"}, {"B5", "35"}, {"BD", "3D"}, {"BE", "3E"},
  {"BF", "3F"}, {"C0", "40"}, {"C1", "41"}, {"C2", "42"}, {"EF", "6F"}, {"F0", "70"},
  {"F1", "71"}, {"F2", "72"}, {"8C", "8B"}, {"0B", "03"}
};

/* ===================== Unattended safety FSM ===================== */
struct RemoteSM {
  bool   latched = false;        // we sent a DOWN that succeeded
  byte   downCmd = 0;
  byte   upCmd   = 0;
  unsigned long holdStart = 0;
  unsigned long holdMs    = 0;   // 0 => ASAP
  byte   upAttempts = 0;
  bool   blocked = false;        // reserved
  bool   requireExplicitUp = false; // Format B “down” needs explicit “up”
};
RemoteSM sm[16];

const unsigned long MAX_HELD_MS     = 3000;
const byte          MAX_UP_RETRIES  = 3;

/* ===================== Prototypes ===================== */
void parseInput(String input);
bool sendKeyCmdAndWaitForAck(int interruptPin, byte keyCmd, unsigned long timeout);
void  releaseAllButtons(int remoteNum);
void  resetRemotes();
void  resetRemote(int remoteNum, int delayMs=500);
int   convertNumToPin(int remoteNum);
static inline byte parseHexByte(const String& s);
static inline int  toIntSafe(const String& s);
static void splitTokens(const String& line, String out[], int& count, int maxTok=8);
static void printHexByte(byte b);
static void printHexBuf(const byte* data, byte len);
void  unattendedTick();
bool  trySendUpFor(int rIdx);
bool  canStartDown(int rIdx);

/* ===================== Setup / Loop ===================== */
void setup() {
  Serial.begin(115200);
  Wire.begin(I2C_SLAVE_ADDR);
  Wire.onRequest(requestEvent);
  Wire.onReceive(receiveEvent);

  for (int i = 0; i < 16; i++) { pinMode(remotePins[i], OUTPUT); digitalWrite(remotePins[i], HIGH); }
  pinMode(RESET_PIN, OUTPUT); digitalWrite(RESET_PIN, HIGH);

  Serial.println("DART (16 remotes) — unified reset for Format A & B, unattended UP enforcement, TX+ACK confirm, timestamped logs");
  Serial.println("Jacob Montgomery - Spreading the JAM 2025-11-11a");
  Serial.flush();
}

void loop() {
  static String inputString = "";
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') { if (inputString.length() > 0) { parseInput(inputString); inputString = ""; } }
    else inputString += c;
  }

  unattendedTick();

  if (debugOn) {
    static uint32_t lastTxTs = 0;
    byte buf[16]; byte len; uint32_t ts;
    noInterrupts();
    bool has = txLogPop(buf, len, ts);
    interrupts();
    while (has) {
      uint32_t dt = (lastTxTs == 0) ? 0 : (ts - lastTxTs);
      lastTxTs = ts;
      Serial.print("[I2C TX @"); Serial.print(ts); Serial.print("us +"); Serial.print(dt); Serial.print("us] ");
      printHexBuf(buf, len); Serial.println();
      noInterrupts(); has = txLogPop(buf, len, ts); interrupts();
    }
  }

  if (debugOn) {
    static uint32_t lastRxTs = 0;
    byte bufR[64]; byte lenR; uint32_t tsR;
    noInterrupts();
    bool hasR = rxLogPop(bufR, lenR, tsR);
    interrupts();
    while (hasR) {
      uint32_t dtR = (lastRxTs == 0) ? 0 : (tsR - lastRxTs);
      lastRxTs = tsR;
      Serial.print("[I2C RX @"); Serial.print(tsR); Serial.print("us +"); Serial.print(dtR); Serial.print("us] ");
      printHexBuf(bufR, lenR); Serial.println();
      noInterrupts(); hasR = rxLogPop(bufR, lenR, tsR); interrupts();
    }
  }
}

/* ===================== Helpers ===================== */
static inline byte parseHexByte(const String& s) {
  String t = s; t.trim(); t.toUpperCase();
  if (t.startsWith("0X")) t = t.substring(2);
  unsigned long v = strtoul(t.c_str(), nullptr, 16);
  return (byte)(v & 0xFF);
}
static inline int toIntSafe(const String& s) { String t=s; t.trim(); return t.toInt(); }
static void splitTokens(const String& line, String out[], int& count, int maxTok) {
  count = 0; int i=0, n=line.length();
  while (i<n && count<maxTok) {
    while (i<n && isspace(line[i])) i++;
    if (i>=n) break;
    int j=i; while (j<n && !isspace(line[j])) j++;
    out[count++] = line.substring(i,j); i=j;
  }
}
static void printHexByte(byte b) { char buf[4]; sprintf(buf, "%02X", b); Serial.print(buf); }
static void printHexBuf(const byte* data, byte len) { for (byte i=0;i<len;i++){ printHexByte(data[i]); if(i<len-1) Serial.print(' '); } }

/* ===================== Unattended safety tick ===================== */
void unattendedTick() {
  const unsigned long now = millis();
  for (int r=0; r<16; ++r) {
    if (!sm[r].latched) continue;

    unsigned long held = now - sm[r].holdStart;

    if (sm[r].requireExplicitUp && held < MAX_HELD_MS) {
      continue; // wait for explicit "up"
    }
    if (!sm[r].requireExplicitUp) {
      if (sm[r].holdMs > 0 && held < sm[r].holdMs) continue;
    }

    if (!trySendUpFor(r)) {
      sm[r].upAttempts++;
      if (sm[r].upAttempts > MAX_UP_RETRIES) {
        if (debugOn) { Serial.print("[FSM] R"); Serial.print(r+1); Serial.println(" UP failed → reset remote"); }
        resetRemote(r+1, 500);
        sm[r] = RemoteSM{};
      }
      delay(5);
    } else {
      sm[r] = RemoteSM{}; // UP accepted
    }
  }
}

bool trySendUpFor(int rIdx) {
  int pin = convertNumToPin(rIdx+1);
  if (pin < 0) return false;
  bool ok = sendKeyCmdAndWaitForAck(pin, sm[rIdx].upCmd, ackTimeout);
  if (!ok && debugOn) {
    Serial.print("[FSM] R"); Serial.print(rIdx+1); Serial.print(" UP retry "); Serial.println(sm[rIdx].upAttempts+1);
  }
  return ok;
}

bool canStartDown(int rIdx) {
  if (sm[rIdx].latched) {
    if (debugOn) { Serial.print("[FSM] R"); Serial.print(rIdx+1); Serial.println(" pending UP → deferring DOWN"); }
    return false;
  }
  if (sm[rIdx].blocked) {
    if (debugOn) { Serial.print("[FSM] R"); Serial.print(rIdx+1); Serial.println(" blocked (recent reset)"); }
    return false;
  }
  return true;
}

/* ===================== Core parsing ===================== */
void parseInput(String input) {
  input.trim();
  if (input.length()==0) return;
  if (debugOn) Serial.println(String("[SER] ")+input);

  // simple console controls
  if (input.equalsIgnoreCase("debug on"))  { debugOn=true;  Serial.println("[DBG] on");  return; }
  if (input.equalsIgnoreCase("debug off")) { debugOn=false; Serial.println("[DBG] off"); return; }
  if (input.startsWith("ack ")) { int v = toIntSafe(input.substring(4)); if (v > 0) { ackTimeout = (unsigned long)v; Serial.print("[ACK] timeout="); Serial.println(ackTimeout);} return; }
  if (input.startsWith("retries ")) { int v = toIntSafe(input.substring(8)); if (v >= 0 && v <= 10) { retriesPerCmd=(byte)v; Serial.print("[RET] retries="); Serial.println(retriesPerCmd);} return; }
  if (input.equalsIgnoreCase("qstat")) { noInterrupts(); uint16_t h=eventHead, t=eventTail; interrupts(); uint16_t fill = (h - t) & EVENT_QUEUE_MASK; Serial.print("[Q] fill="); Serial.print(fill); Serial.print("/"); Serial.println(EVENT_QUEUE_SIZE); return; }
  if (input.equalsIgnoreCase("reset")) { resetRemotes(); return; } // global

  String tok[8]; int ntok=0; splitTokens(input, tok, ntok, 8);

  /* -------- Per-remote reset (works for both A & B semantics) --------
     1) "<remote> reset [delayMs]"  (already supported)
  */
  if (ntok >= 2 && tok[1].equalsIgnoreCase("reset")) {
    int remoteNum = toIntSafe(tok[0]); int delayMs = (ntok >= 3) ? toIntSafe(tok[2]) : 500;
    resetRemote(remoteNum, delayMs);
    if (remoteNum >= 1 && remoteNum <= 16) sm[remoteNum-1] = RemoteSM{};
    return;
  }

  /* -------- Format A: remoteNum keyDown keyUp delayMs --------
     Now also accepts "reset" in either key slot to perform per-remote reset.
  */
  if (ntok == 4) {
    int  remoteNum   = toIntSafe(tok[0]);
    bool isDownReset = tok[1].equalsIgnoreCase("reset");
    bool isUpReset   = tok[2].equalsIgnoreCase("reset");

    // Fast-path: treat "reset" in any key slot as per-remote reset
    if (isDownReset || isUpReset) {
      int delayMs = toIntSafe(tok[3]);
      resetRemote(remoteNum, (delayMs>0?delayMs:500));
      if (remoteNum >= 1 && remoteNum <= 16) sm[remoteNum-1] = RemoteSM{};
      return;
    }

    // Regular Format A flow
    byte keyCmdDown  = parseHexByte(tok[1]);
    byte keyCmdUp    = parseHexByte(tok[2]);
    int  delayMs     = toIntSafe(tok[3]);
    int  pin         = convertNumToPin(remoteNum);
    if (pin < 0) { if (debugOn) Serial.println("[ERR] bad remoteNum"); return; }
    int rIdx = remoteNum-1;

    if (!canStartDown(rIdx)) { return; }

    if (debugOn) {
      Serial.print("[CMD-A] R"); Serial.print(remoteNum);
      Serial.print(" DOWN=0x"); printHexByte(keyCmdDown);
      Serial.print(" UP=0x");   printHexByte(keyCmdUp);
      Serial.print(" delay=");  Serial.println(delayMs);
    }

    bool downOk = false;
    for (byte attempt=0; attempt<=retriesPerCmd; ++attempt) {
      if (sendKeyCmdAndWaitForAck(pin, keyCmdDown, ackTimeout)) { downOk = true; break; }
      if (attempt==retriesPerCmd) { if (debugOn) Serial.println("[ERR] DOWN failed"); return; }
      delay(5);
    }

    if (downOk) {
      sm[rIdx].latched           = true;
      sm[rIdx].downCmd           = keyCmdDown;
      sm[rIdx].upCmd             = keyCmdUp;
      sm[rIdx].holdStart         = millis();
      sm[rIdx].holdMs            = (delayMs < 0 ? 0 : (unsigned long)delayMs);
      sm[rIdx].upAttempts        = 0;
      sm[rIdx].requireExplicitUp = false;

      if (sm[rIdx].holdMs == 0) (void)trySendUpFor(rIdx);
    } else {
      if (debugOn) Serial.println("[SKIP] UP skipped because DOWN never succeeded");
    }
    return;
  }

  /* -------- Format B: remoteNum buttonNum action --------
     Enhancements:
       • action == "reset" → per-remote reset (buttonNum ignored, 99 still accepted)
       • action == "allup" → release all buttons (buttonNum ignored, 86 still accepted)
       • buttonNum == 99   → per-remote reset (consistent with "action=reset")
       • buttonNum == 86   → release all buttons (action ignored)
  */
  if (ntok == 3) {
    int remoteNum = toIntSafe(tok[0]);
    int buttonNum = toIntSafe(tok[1]);
    String action = tok[2]; action.trim(); action.toLowerCase();

    // Unified "all up"
    if (action == "allup" || buttonNum == 86) { releaseAllButtons(remoteNum); return; }

    // Unified "reset" (per-remote)
    if (action == "reset" || buttonNum == 99) {
      int delayMs = 500;
      if (debugOn) { Serial.print("[RST] per-remote via Format B, R="); Serial.println(remoteNum); }
      resetRemote(remoteNum, delayMs);
      if (remoteNum>=1 && remoteNum<=16) sm[remoteNum-1] = RemoteSM{};
      return;
    }

    if (buttonNum <= 0 || buttonNum > 40) { if (debugOn) Serial.println("[ERR] bad buttonNum"); return; }
    int pin = convertNumToPin(remoteNum);
    if (pin < 0) { if (debugOn) Serial.println("[ERR] bad remoteNum"); return; }
    int rIdx = remoteNum-1;

    if (action == "down") {
      if (!canStartDown(rIdx)) return;
      byte down = parseHexByte(String(buttonActions[buttonNum - 1][0]));
      byte up   = parseHexByte(String(buttonActions[buttonNum - 1][1]));

      bool downOk=false;
      for (byte attempt=0; attempt<=retriesPerCmd; ++attempt) {
        if (sendKeyCmdAndWaitForAck(pin, down, ackTimeout)) { downOk=true; break; }
        if (attempt==retriesPerCmd) { if (debugOn) Serial.println("[ERR] DOWN failed"); return; }
        delay(5);
      }
      if (downOk) {
        sm[rIdx].latched           = true;
        sm[rIdx].downCmd           = down;
        sm[rIdx].upCmd             = up;
        sm[rIdx].holdStart         = millis();
        sm[rIdx].holdMs            = 0;
        sm[rIdx].upAttempts        = 0;
        sm[rIdx].requireExplicitUp = true; // Format B “down” requires explicit “up”
      }
      return;

    } else if (action == "up") {
      byte up = parseHexByte(String(buttonActions[buttonNum - 1][1]));
      sm[rIdx].upCmd             = up;
      sm[rIdx].requireExplicitUp = false;
      if (!sm[rIdx].latched) {
        sm[rIdx].latched   = true;
        sm[rIdx].downCmd   = 0;
        sm[rIdx].holdStart = millis();
        sm[rIdx].holdMs    = 0;
        sm[rIdx].upAttempts= 0;
      }
      (void)trySendUpFor(rIdx);
      return;

    } else {
      if (debugOn) Serial.println("[ERR] invalid action"); return;
    }
  }

  Serial.print("[ERR] Failed to parse: "); Serial.println(input);
}

/* ===================== Trigger / TX+ACK wait ===================== */
bool sendKeyCmdAndWaitForAck(int interruptPin, byte keyCmd, unsigned long timeout) {
  ackReceived = false;
  txSeenForCmd = false;
  waitForCmd = keyCmd;

  KEY_CMD = keyCmd;
  noInterrupts();
  if (eventFull()) { interrupts(); if (debugOn) Serial.println("[Q] full; drop"); return false; }
  eventEnq_isrSafe(keyCmd);
  interrupts();

  if (debugOn) { Serial.print("[TRIG] pin="); Serial.print(interruptPin); Serial.print(" key=0x"); printHexByte(keyCmd); Serial.println(" (LOW→HIGH)"); }
  digitalWrite(interruptPin, LOW);
  delay(2);
  digitalWrite(interruptPin, HIGH);

  unsigned long startTime = millis();
  while (true) {
    bool sawTx, sawAck;
    noInterrupts(); sawTx = txSeenForCmd; sawAck = ackReceived; interrupts();
    if (sawTx && sawAck) break;
    if (millis() - startTime > timeout) {
      if (debugOn) {
        Serial.print("[WAIT] timeout; sawTx="); Serial.print(sawTx); Serial.print(" sawAck="); Serial.println(sawAck);
      }
      return false;
    }
  }
  if (debugOn) Serial.println("[TRIG] TX+ACK confirmed");
  return true;
}

/* ===================== Release / Reset ===================== */
void releaseAllButtons(int remoteNum) {
  int pin = convertNumToPin(remoteNum);
  if (pin < 0) { if (debugOn) Serial.println("[REL] invalid remote"); return; }
  byte up = 0x03; // generic UP
  for (byte attempt=0; attempt<=retriesPerCmd; ++attempt) {
    if (sendKeyCmdAndWaitForAck(pin, up, ackTimeout)) break;
    if (attempt==retriesPerCmd) { if (debugOn) Serial.println("[REL] failed"); return; }
    delay(5);
  }
  if (remoteNum>=1 && remoteNum<=16) sm[remoteNum-1] = RemoteSM{};
}

void resetRemotes() {
  if (debugOn) Serial.println("[RST] ALL remotes (RESET_PIN)");
  digitalWrite(RESET_PIN, LOW);
  delay(500);
  digitalWrite(RESET_PIN, HIGH);
  for (int i=0;i<16;i++) sm[i] = RemoteSM{};
}

void resetRemote(int remoteNum, int delayMs) {
  int pin = convertNumToPin(remoteNum);
  if (pin < 0) { if (debugOn) Serial.println("[RST] invalid remote"); return; }
  if (debugOn) { Serial.print("[RST] remote "); Serial.print(remoteNum); Serial.print(" for "); Serial.print(delayMs); Serial.println(" ms"); }
  digitalWrite(pin, LOW);
  delay(delayMs);
  digitalWrite(pin, HIGH);
}

/* ===================== I2C handlers ===================== */
void requestEvent() {
  byte keyOut = 0x00;
  (void)eventDeq_isrSafe(keyOut);

  byte out[16]; byte n = 0;
  if (clearInterruptFlag) { out[n++] = BLANK; clearInterruptFlag = false; }
  else                    { out[n++] = 0xAF; }
  out[n++] = INT_REG;
  out[n++] = EVT_REG;
  out[n++] = keyOut;
  for (int i = 0; i < 11; i++) out[n++] = BLANK;

  for (byte i=0;i<n;i++) Wire.write(out[i]);

  if (out[3] == waitForCmd) { txSeenForCmd = true; }

  txLogPush(out, n, micros());
}

void receiveEvent(int howMany) {
  byte buf[64]; byte i=0;
  byte command = 0;
  byte lastByte = 0;

  if (Wire.available()) { command = Wire.read(); buf[i++] = command; }
  while (Wire.available() && i < sizeof(buf)) { lastByte = Wire.read(); buf[i++] = lastByte; }

  if (initFlag && command == 0x01) { CFG_REG = lastByte; initFlag = false; }
  else if (command == 0x02) { clearInterruptFlag = true; ackReceived = true; }

  rxLogPush(buf, i, micros());
}

/* ===================== Pin mapping ===================== */
int convertNumToPin(int remoteNum) {
  if (remoteNum >= 1 && remoteNum <= 16) return remotePins[remoteNum - 1];
  return -1;
}
