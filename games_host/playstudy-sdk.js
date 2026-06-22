/*!
 * PlayStudy Game SDK — v1
 * -----------------------------------------------------------------------------
 * The single contract every PlayStudy game bundle speaks. Include it once:
 *
 *     <script src="../../playstudy-sdk.js"></script>
 *
 * It hides the transport difference between the two hosts:
 *   • Mobile  — a `PlayStudy` JavaScript channel injected by the app's WebView.
 *   • Web     — `postMessage` to the parent window of the embedding <iframe>.
 *
 * A game written against this SDK runs unchanged on mobile and web, with no
 * game logic in the app — that is the whole point.
 *
 * Lifecycle
 *   1. The SDK reads the study set's content (quiz/words) from the launch URL,
 *      and also accepts it pushed by the host after load.
 *   2. Register `PlayStudyGame.onInit(cb)` to receive `{quiz, words}`.
 *   3. Report play with `score()`, `progress()`, `reward()`, `gameover()`.
 */
(function () {
  'use strict';

  var SDK_VERSION = 1;

  // --- transport ------------------------------------------------------------
  // The mobile app injects a `PlayStudy` channel exposing postMessage(string).
  // Its presence is how we tell mobile from web.
  var channel =
    window.PlayStudy && typeof window.PlayStudy.postMessage === 'function'
      ? window.PlayStudy
      : null;
  var isMobile = !!channel;

  function send(type, data) {
    var msg = {};
    if (data) {
      for (var k in data) {
        if (Object.prototype.hasOwnProperty.call(data, k)) msg[k] = data[k];
      }
    }
    msg.type = type;
    msg.sdkVersion = SDK_VERSION;
    var json = JSON.stringify(msg);
    if (isMobile) {
      channel.postMessage(json);
    } else if (window.parent && window.parent !== window) {
      window.parent.postMessage(json, '*');
    }
  }

  // --- material (quiz / words) ----------------------------------------------
  function decodeParam(name) {
    try {
      var raw = new URLSearchParams(window.location.search).get(name);
      if (!raw) return null;
      // base64url -> base64 -> UTF-8 JSON
      var b64 = raw.replace(/-/g, '+').replace(/_/g, '/');
      var bytes = atob(b64);
      var json = decodeURIComponent(
        bytes
          .split('')
          .map(function (c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
          })
          .join('')
      );
      return JSON.parse(json);
    } catch (e) {
      return null;
    }
  }

  var material = {
    quiz: decodeParam('quiz') || [],
    words: decodeParam('words') || [],
  };

  var initCb = null;

  function fireInit() {
    if (typeof initCb === 'function') initCb(material);
  }

  function applyPayload(payload) {
    if (!payload) return;
    if (Array.isArray(payload.quiz)) material.quiz = payload.quiz;
    if (Array.isArray(payload.words)) material.words = payload.words;
    fireInit();
  }

  // Mobile: the host calls window.PlayStudyInit(payload) after the page loads.
  window.PlayStudyInit = function (payload) {
    applyPayload(payload);
  };

  // Web: the host posts {type:'init', payload} from the parent window.
  window.addEventListener('message', function (ev) {
    var d = ev.data;
    if (typeof d === 'string') {
      try {
        d = JSON.parse(d);
      } catch (e) {
        return;
      }
    }
    if (d && d.type === 'init') applyPayload(d.payload);
  });

  // --- public API -----------------------------------------------------------
  window.PlayStudyGame = {
    version: SDK_VERSION,

    /** The study set content for this play: { quiz: [...], words: [...] }. */
    get material() {
      return material;
    },

    /**
     * Register a callback to receive {quiz, words}. Fires immediately if the
     * content arrived in the launch URL, and again if the host pushes it.
     */
    onInit: function (cb) {
      initCb = cb;
      if (material.quiz.length || material.words.length) {
        setTimeout(fireInit, 0);
      }
    },

    /** Ask the host to (re)send the init payload. */
    ready: function () {
      send('ready');
    },

    /** Report the current score. */
    score: function (n) {
      send('score', { score: n | 0 });
    },

    /** Persist an opaque save-state blob so the play can resume later. */
    progress: function (state) {
      send('progress', { state: state });
    },

    /** Request a gameplay reward (the server recomputes + caps the points). */
    reward: function (reason) {
      send('reward', { reason: String(reason || '') });
    },

    /** End the play with a final score; the server grants the completion reward. */
    gameover: function (score) {
      send('gameover', { score: score | 0 });
    },

    /** Report a fatal error to the host. */
    error: function (message) {
      send('error', { message: String(message || '') });
    },
  };

  // Announce readiness as soon as the SDK loads.
  send('ready');
})();
