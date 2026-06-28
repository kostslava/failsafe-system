#include <Arduino_LED_Matrix.h>
#include <Arduino_RouterBridge.h>
#include <cstring>

static constexpr int ROWS = 8;
static constexpr int COLS = 13;
static constexpr int FRAME_SIZE = ROWS * COLS;

ArduinoLEDMatrix matrix;
uint8_t frame[FRAME_SIZE];

enum DisplayMode : uint8_t {
  MODE_OK = 0,
  MODE_THINKING = 1,
  MODE_FAIL = 2,
};

volatile DisplayMode currentMode = MODE_OK;
char serialLine[32];
uint8_t serialLineLen = 0;

unsigned long lastAnimTickMs = 0;
unsigned long lastFailFlashMs = 0;
uint8_t spinnerStep = 0;
bool failFlashOn = false;

static const uint8_t PATTERN_CHECKMARK[FRAME_SIZE] = {
  0, 0, 0, 0, 0, 0, 0, 255, 0, 0, 0, 0, 0,
  0, 0, 0, 0, 0, 0, 255, 0, 255, 0, 0, 0, 0, 0,
  0, 0, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0,
  0, 0, 0, 0, 255, 0, 0, 0, 0, 0, 255, 0, 0,
  0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0,
  0, 0, 0, 0, 255, 0, 0, 0, 0, 255, 0, 0, 0,
  0, 0, 0, 0, 0, 255, 0, 255, 255, 0, 0, 0, 0,
  0, 0, 0, 0, 0, 0, 255, 255, 255, 0, 0, 0, 0,
};

static const uint8_t PATTERN_X[FRAME_SIZE] = {
  255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 255,
  0, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 255, 0,
  0, 0, 255, 0, 0, 0, 0, 0, 0, 0, 255, 0, 0,
  0, 0, 0, 255, 0, 0, 0, 0, 0, 255, 0, 0, 0,
  0, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 0,
  0, 0, 0, 0, 0, 255, 0, 255, 0, 0, 0, 0, 0,
  0, 0, 0, 0, 0, 0, 255, 0, 0, 0, 0, 0, 0,
  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
};

void clearFrame() {
  memset(frame, 0, FRAME_SIZE);
}

void blitPattern(const uint8_t *pattern, uint8_t brightness) {
  for (int i = 0; i < FRAME_SIZE; i++) {
    frame[i] = pattern[i] ? brightness : 0;
  }
}

void applyCommand(const char *command) {
  if (strcmp(command, "STATUS_OK") == 0) {
    currentMode = MODE_OK;
    blitPattern(PATTERN_CHECKMARK, 255);
    matrix.draw(frame);
    return;
  }

  if (strcmp(command, "STATUS_THINKING") == 0) {
    currentMode = MODE_THINKING;
    spinnerStep = 0;
    lastAnimTickMs = millis();
    return;
  }

  if (strcmp(command, "STATUS_FAIL") == 0) {
    currentMode = MODE_FAIL;
    failFlashOn = true;
    lastFailFlashMs = millis();
    blitPattern(PATTERN_X, 255);
    matrix.draw(frame);
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

  if (currentMode == MODE_OK) {
    return;
  }

  if (currentMode == MODE_THINKING) {
    if (now - lastAnimTickMs >= 120) {
      lastAnimTickMs = now;
      spinnerStep = (spinnerStep + 1) % 24;
      drawSpinner(spinnerStep);
    }
    return;
  }

  if (currentMode == MODE_FAIL) {
    if (now - lastFailFlashMs >= 250) {
      lastFailFlashMs = now;
      failFlashOn = !failFlashOn;
      if (failFlashOn) {
        blitPattern(PATTERN_X, 255);
      } else {
        clearFrame();
      }
      matrix.draw(frame);
    }
  }
}

void setup() {
  Serial.begin(115200);
  matrix.begin();
  matrix.setGrayscaleBits(8);

  Bridge.begin();
  Bridge.provide_safe("status_command", handleStatusCommand);

  currentMode = MODE_OK;
  blitPattern(PATTERN_CHECKMARK, 255);
  matrix.draw(frame);
}

void loop() {
  processSerialInput();
  updateAnimation();
}
