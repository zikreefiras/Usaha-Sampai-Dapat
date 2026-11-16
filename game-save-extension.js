(function(Scratch) {
  "use strict";

  if (!Scratch.extensions.unsandboxed) {
    throw new Error("The SINCA save bridge must run unsandboxed.");
  }

  const vm = Scratch.vm;
  const parentOrigin = getParentOrigin();
  const variableNames = {
    money: "☁ money",
    level: "☁ level",
    device: "☁ deviceLast"
  };
  let restored = false;
  let previousState = null;
  let restoreGuardUntil = 0;
  let readinessTimer = null;

  function getParentOrigin() {
    try {
      if (document.referrer) return new URL(document.referrer).origin;
      if (window.location.ancestorOrigins && window.location.ancestorOrigins.length) {
        return window.location.ancestorOrigins[0];
      }
    } catch (error) {
      console.error("Could not determine launcher origin.", error);
    }
    return "";
  }

  function getStageVariables() {
    const stage = vm.runtime.targets.find(function(target) {
      return target.isStage;
    });
    if (!stage) return null;

    const byName = {};
    Object.values(stage.variables).forEach(function(variable) {
      byName[variable.name] = variable;
    });

    const vars = {
      money: byName[variableNames.money],
      level: byName[variableNames.level],
      device: byName[variableNames.device]
    };
    return vars.money && vars.level && vars.device ? vars : null;
  }

  function validState(value) {
    if (!value || typeof value !== "object") return null;
    const money = Number(value.money);
    const level = Number(value.level);
    const device = String(value.device);
    if (!Number.isFinite(money) || money < 0 || !Number.isInteger(level) || level < 0) {
      return null;
    }
    if (device !== "1" && device !== "2") return null;
    return { money: String(money), level: String(level), device: device };
  }

  function readState(vars) {
    return validState({
      money: vars.money.value,
      level: vars.level.value,
      device: vars.device.value
    });
  }

  function sendToLauncher(type, payload) {
    if (!parentOrigin) return;
    window.parent.postMessage(
      { source: "sinca-game-save", type: type, payload: payload },
      parentOrigin
    );
  }

  function announceReady() {
    if (readinessTimer) {
      clearInterval(readinessTimer);
      readinessTimer = null;
    }
    sendToLauncher("ready");
  }

  function tryAnnounceReady() {
    if (getStageVariables()) {
      announceReady();
      return true;
    }
    return false;
  }

  function applyState(state) {
    const normalized = validState(state);
    const vars = getStageVariables();
    if (!normalized || !vars) return false;
    vars.money.value = normalized.money;
    vars.level.value = normalized.level;
    vars.device.value = normalized.device;
    previousState = normalized;
    restoreGuardUntil = Date.now() + 5000;
    restored = true;
    return true;
  }

  function monitorProgress() {
    if (!restored) return;
    const vars = getStageVariables();
    if (!vars) return;

    let state = readState(vars);
    if (!state) return;

    if (Date.now() < restoreGuardUntil && previousState) {
      if (state.money === "0" && Number(previousState.money) > 0) {
        vars.money.value = previousState.money;
      }
      if (state.level === "0" && Number(previousState.level) > 0) {
        vars.level.value = previousState.level;
      }
      state = readState(vars);
      if (!state) return;
    }

    const serialized = JSON.stringify(state);
    if (serialized !== JSON.stringify(previousState)) {
      previousState = state;
      sendToLauncher("state", state);
    }
  }

  window.addEventListener("message", function(event) {
    if (event.source !== window.parent || event.origin !== parentOrigin) return;
    const message = event.data;
    if (!message || message.source !== "sinca-launcher") return;

    if (message.type === "restore") {
      if (applyState(message.payload)) {
        sendToLauncher("restored", previousState);
      } else {
        sendToLauncher("error", { message: "Could not restore the saved game data." });
      }
    } else if (message.type === "save-now") {
      const vars = getStageVariables();
      const state = vars && readState(vars);
      if (state) sendToLauncher("state", state);
      else sendToLauncher("error", { message: "Game progress is not ready to save." });
    }
  });

  class WebsiteSaveBridge {
    getInfo() {
      return {
        id: "sincaWebsiteSave",
        name: "Website Save",
        blocks: [
          {
            opcode: "saveNow",
            blockType: Scratch.BlockType.COMMAND,
            text: "save game progress to website"
          }
        ]
      };
    }

    saveNow() {
      const vars = getStageVariables();
      const state = vars && readState(vars);
      if (state) sendToLauncher("state", state);
    }
  }

  Scratch.extensions.register(new WebsiteSaveBridge());

  if (!tryAnnounceReady()) {
    readinessTimer = setInterval(tryAnnounceReady, 200);
  }
  setInterval(monitorProgress, 500);
})(Scratch);
