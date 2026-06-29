#include <Arduino_LED_Matrix.h>
#include <Arduino_RouterBridge.h>
#include <cstring>

static constexpr int ROWS = 8;
static constexpr int COLS = 13;
static constexpr int FRAME_SIZE = ROWS * COLS;
static constexpr int CHAR_WIDTH = 6;
static constexpr int GLYPH_ROWS = 7;
static constexpr unsigned long SCROLL_MS = 180;

ArduinoLEDMatrix matrix;
uint8_t frame[FRAME_SIZE];

enum DisplayMode : uint8_t {
  MODE_SCROLL = 0,
  MODE_THINKING = 1,
};

volatile DisplayMode currentMode = MODE_SCROLL;
char scrollText[16] = "SAFE";
char serialLine[32];
uint8_t serialLineLen = 0;

unsigned long lastAnimTickMs = 0;
uint8_t spinnerStep = 0;
int scrollOffset = 0;

struct Glyph {
  char letter;
  uint8_t columns[5];
};

static const Glyph FONT[] = {
  {'A', {0x7E, 0x11, 0x11, 0x11, 0x7E}},
  {'D', {0x7F, 0x41, 0x41, 0x41, 0x7F}},
  {'E', {0x7F, 0x49, 0x49, 0x49, 0x41}},
  {'F', {0x7F, 0x09, 0x09, 0x09, 0x01}},
  {'H', {0x7F, 0x08, 0x08, 0x08, 0x7F}},
  {'L', {0x7F, 0x01, 0x01, 0x01, 0x01}},
  {'S', {0x46, 0x49, 0x49, 0x49, 0x31}},
  {'T', {0x01, 0x01, 0x7F, 0x01, 0x01}},
  {' ', {0x00, 0x00, 0x00, 0x00, 0x00}},
};

void clearFrame() {
  memset(frame, 0, FRAME_SIZE);
}

const uint8_t *lookupGlyph(char letter) {
  for (const Glyph &glyph : FONT) {
    if (glyph.letter == letter) {
      return glyph.columns;
    }
  }
  return FONT[8].columns;
}

void drawGlyph(int startCol, char letter) {
  const uint8_t *columns = lookupGlyph(letter);
  for (int col = 0; col < 5; col++) {
    uint8_t bits = columns[col];
    for (int row = 0; row < GLYPH_ROWS; row++) {
      if (bits & (1 << row)) {
        int targetRow = row + 1;
        int targetCol = startCol + col;
        if (targetRow >= 0 && targetRow < ROWS && targetCol >= 0 && targetCol < COLS) {
          frame[targetRow * COLS + targetCol] = 255;
        }
      }
    }
  }
}

void drawMessageAt(int startCol, const char *text) {
  int x = startCol;
  for (int i = 0; text[i] != '\0'; i++) {
    drawGlyph(x, text[i]);
    x += CHAR_WIDTH;
  }
}

int messagePixelWidth() {
  return static_cast<int>(strlen(scrollText)) * CHAR_WIDTH;
}

void drawScrollingText() {
  clearFrame();
  const int width = messagePixelWidth();
  if (width <= 0) {
    matrix.draw(frame);
    return;
  }

  const int loopWidth = width + COLS;
  const int offset = scrollOffset % loopWidth;

  drawMessageAt(COLS - offset, scrollText);
  drawMessageAt(COLS - offset + width + CHAR_WIDTH, scrollText);
  matrix.draw(frame);
}

void setScrollMessage(const char *text) {
  strncpy(scrollText, text, sizeof(scrollText) - 1);
  scrollText[sizeof(scrollText) - 1] = '\0';
  scrollOffset = 0;
  currentMode = MODE_SCROLL;
  drawScrollingText();
}

void applyCommand(const char *command) {
  if (strcmp(command, "STATUS_OK") == 0) {
    setScrollMessage("SAFE");
    return;
  }

  if (strcmp(command, "STATUS_THINKING") == 0) {
    currentMode = MODE_THINKING;
    spinnerStep = 0;
    lastAnimTickMs = millis();
    return;
  }

  if (strcmp(command, "STATUS_FAIL") == 0) {
    setScrollMessage("HALTED");
  }
}

void handleStatusCommand(String command) {
  command.trim();
  if (command.length() == 0 || command.length() >= (int)sizeof(serialLine)) {
    return;
  }
  command.toCharArray(serialLine, sizeof(serialLine));
  applyCommand(serialLine);
}

void processSerialInput() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (serialLineLen > 0) {
        serialLine[serialLineLen] = '\0';
        applyCommand(serialLine);
        serialLineLen = 0;
      }
      continue;
    }

    if (serialLineLen < (sizeof(serialLine) - 1)) {
      serialLine[serialLineLen++] = c;
    }
  }
}

void drawSpinner(uint8_t step) {
  clearFrame();
  const int perimeter[24][2] = {
    {0, 0}, {0, 1}, {0, 2}, {0, 3}, {0, 4}, {0, 5}, {0, 6}, {0, 7}, {0, 8}, {0, 9}, {0, 10}, {0, 11}, {0, 12},
    {1, 12}, {2, 12}, {3, 12}, {4, 12}, {5, 12}, {6, 12}, {7, 12},
    {7, 11}, {7, 10}, {7, 9}, {7, 8},
  };

  const int count = sizeof(perimeter) / sizeof(perimeter[0]);
  for (int i = 0; i < 3; i++) {
    int idx = (step + i) % count;
    int row = perimeter[idx][0];
    int col = perimeter[idx][1];
    frame[row * COLS + col] = static_cast<uint8_t>(255 - (i * 70));
  }
  matrix.draw(frame);
}

void updateAnimation() {
  unsigned long now = millis();

  if (currentMode == MODE_THINKING) {
    if (now - lastAnimTickMs >= 120) {
      lastAnimTickMs = now;
      spinnerStep = (spinnerStep + 1) % 24;
      drawSpinner(spinnerStep);
    }
    return;
  }

  if (now - lastAnimTickMs >= SCROLL_MS) {
    lastAnimTickMs = now;
    scrollOffset++;
    drawScrollingText();
  }
}

void setup() {
  Serial.begin(115200);
  matrix.begin();
  matrix.setGrayscaleBits(8);

  Bridge.begin();
  Bridge.provide_safe("status_command", handleStatusCommand);

  setScrollMessage("SAFE");
}

void loop() {
  processSerialInput();
  updateAnimation();
}
