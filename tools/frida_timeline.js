// Frida timeline for KHUx v1.0.1 — logs scene transitions, API actions, and battle setup
// Usage: frida -U -l frida_timeline.js -f com.square_enix.android_googleplay.khuxww
//    or: frida -H 192.168.1.181:27042 -l frida_timeline.js -f com.square_enix.android_googleplay.khuxww

var libName = "libcocos2dcpp.so";
var t0 = null;

function ts() {
    if (!t0) t0 = Date.now();
    var elapsed = ((Date.now() - t0) / 1000).toFixed(3);
    return "[+" + elapsed + "s]";
}

function waitForLib(callback) {
    var mod = Process.findModuleByName(libName);
    if (mod) {
        callback(mod);
    } else {
        var timer = setInterval(function () {
            mod = Process.findModuleByName(libName);
            if (mod) {
                clearInterval(timer);
                callback(mod);
            }
        }, 500);
    }
}

waitForLib(function (mod) {
    var base = mod.base;
    t0 = Date.now();
    console.log(ts() + " libcocos2dcpp.so at " + base);

    // ── Scene init hooks ──────────────────────────────────────────────
    var scenes = [
        [0x67D8D0, "SceneTitle::init"],
        [0x714EEC, "SceneAgreement::init"],
        [0x73A238, "SceneTutorialDownload::init"],
        [0x6C7F60, "SceneDownload::init"],
        [0x716E40, "SceneNameRegister::init"],
        [0x703F7C, "SceneAvatarEdit::init"],
        [0x638D88, "SceneMovie::init"],
        [0x71734C, "SceneUnionRegister::init"],
        [0x6C8E08, "SceneSelectUnion::init"],
        [0x5FBA70, "SceneActionMap::init"],
    ];

    scenes.forEach(function (pair) {
        try {
            Interceptor.attach(base.add(pair[0] + 1), {
                onEnter: function () {
                    console.log(ts() + " >>> SCENE: " + pair[1]);
                },
            });
        } catch (e) {
            console.log("[!] Failed to hook " + pair[1] + ": " + e);
        }
    });

    // ── Director scene changes ────────────────────────────────────────
    try {
        Interceptor.attach(base.add(0x8F071E + 1), {
            onEnter: function () {
                console.log(ts() + " Director::replaceScene");
            },
        });
    } catch (e) {
        console.log("[!] replaceScene hook failed: " + e);
    }
    try {
        Interceptor.attach(base.add(0x8F06FA + 1), {
            onEnter: function () {
                console.log(ts() + " Director::pushScene");
            },
        });
    } catch (e) {
        console.log("[!] pushScene hook failed: " + e);
    }

    // ── API hooks ─────────────────────────────────────────────────────
    // APIManager::onRespond(this, actionId, statusCode, ...)
    try {
        Interceptor.attach(base.add(0x4BAF7C + 1), {
            onEnter: function (args) {
                var action = args[1].toInt32();
                var status = args[2].toInt32();
                console.log(
                    ts() + " API onRespond  action=" + action + "  status=" + status
                );
            },
        });
    } catch (e) {
        console.log("[!] onRespond hook failed: " + e);
    }

    // hole::network::api::Client::requestAPI — outgoing requests
    try {
        Interceptor.attach(base.add(0x4B7920 + 1), {
            onEnter: function (args) {
                // args[0] = this (Client), args[1] = Request&
                // Request struct has action as first int field
                try {
                    var reqPtr = args[1];
                    var action = reqPtr.readS32();
                    console.log(ts() + " API requestAPI  action=" + action);
                } catch (e2) {
                    console.log(ts() + " API requestAPI  (can't read action)");
                }
            },
        });
    } catch (e) {
        console.log("[!] requestAPI hook failed: " + e);
    }

    // ── Popup hooks ───────────────────────────────────────────────────
    try {
        Interceptor.attach(base.add(0x563344 + 1), {
            onEnter: function () {
                console.log(ts() + " PopupRegister::openBirthRegisterPopup");
            },
        });
    } catch (e) {
        console.log("[!] birthPopup hook failed: " + e);
    }
    try {
        Interceptor.attach(base.add(0x56549C + 1), {
            onEnter: function () {
                console.log(ts() + " PopupRegister::openNameRegisterPopup");
            },
        });
    } catch (e) {
        console.log("[!] namePopup hook failed: " + e);
    }

    // ── Download hooks ─────────────────────────────────────────────────
    try {
        Interceptor.attach(base.add(0x73A484 + 1), {
            onEnter: function () {
                console.log(ts() + " SceneTutorialDownload::openDownloadPopup");
            },
        });
    } catch (e) {
        console.log("[!] openDownloadPopup hook failed: " + e);
    }
    try {
        Interceptor.attach(base.add(0x73ABBC + 1), {
            onEnter: function () {
                console.log(ts() + " >>> SceneTutorialDownload::openJewelPopup (download complete!)");
            },
        });
    } catch (e) {
        console.log("[!] openJewelPopup hook failed: " + e);
    }

    // ── Union hooks ──────────────────────────────────────────────────
    try {
        Interceptor.attach(base.add(0x6C9740 + 1), {
            onEnter: function () {
                console.log(ts() + " SceneSelectUnion::openPopUpDescriptionUnion (I understand)");
            },
        });
    } catch (e) {
        console.log("[!] openPopUpDescriptionUnion hook failed: " + e);
    }
    try {
        Interceptor.attach(base.add(0x6CA060 + 1), {
            onEnter: function () {
                console.log(ts() + " SceneSelectUnion::openPopUpUnion (select union)");
            },
        });
    } catch (e) {
        console.log("[!] openPopUpUnion hook failed: " + e);
    }

    try {
        Interceptor.attach(base.add(0x717CC8 + 1), {
            onEnter: function () {
                console.log(ts() + " SceneUnionRegister::openPopUpbeLongToUnion (Join Unicornis?)");
            },
        });
    } catch (e) {
        console.log("[!] openPopUpbeLongToUnion hook failed: " + e);
    }

    // ── Battle hooks ──────────────────────────────────────────────────
    try {
        Interceptor.attach(base.add(0x71792C + 1), {
            onEnter: function () {
                console.log(
                    ts() +
                        " >>> SceneUnionRegister::callTutorialStageStartAPI"
                );
            },
        });
    } catch (e) {
        console.log("[!] callTutorialStageStartAPI hook failed: " + e);
    }
    try {
        Interceptor.attach(base.add(0x717A08 + 1), {
            onEnter: function () {
                console.log(ts() + " >>> SceneUnionRegister::startTutorialStage");
            },
        });
    } catch (e) {
        console.log("[!] startTutorialStage hook failed: " + e);
    }
    try {
        Interceptor.attach(base.add(0x759068 + 1), {
            onEnter: function (args) {
                var stageId = args[1].toInt32();
                console.log(
                    ts() + " >>> StageManager::stageFirstSetup  stageId=" + stageId
                );
            },
        });
    } catch (e) {
        console.log("[!] stageFirstSetup hook failed: " + e);
    }

    // ── SceneActionMap loading substates ──────────────────────────────
    try {
        Interceptor.attach(base.add(0x5FCFFC + 1), {
            onEnter: function () {
                console.log(ts() + " SceneActionMap::updateLoadingMode");
            },
        });
    } catch (e) {}
    try {
        Interceptor.attach(base.add(0x5FE9F8 + 1), {
            onEnter: function () {
                console.log(ts() + " SceneActionMap::updateFieldMode");
            },
        });
    } catch (e) {}

    console.log(ts() + " All hooks installed. Waiting for game activity...");
});
