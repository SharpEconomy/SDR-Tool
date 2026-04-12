(function () {
  const loginButton = document.querySelector("[data-firebase-login]");
  const logoutForm = document.querySelector("[data-firebase-logout-form]");
  const feedbackNode = document.querySelector("[data-auth-feedback]");
  const configNode = document.getElementById("firebase-client-config");
  const serverAuthenticated =
    document
      .querySelector('meta[name="server-authenticated"]')
      ?.getAttribute("content") === "true";
  const host = window.location.hostname;
  const isLocalHost =
    host === "localhost" || host === "127.0.0.1" || host === "::1";
  let loginInFlight = false;

  if (!configNode) {
    return;
  }

  const config = JSON.parse(configNode.textContent);
  const csrfToken = getCsrfToken();

  if (!firebase.apps.length) {
    firebase.initializeApp(config);
  }

  const auth = firebase.auth();

  auth
    .setPersistence(firebase.auth.Auth.Persistence.LOCAL)
    .catch(function () {
      setFeedback("Failed to enable session persistence.");
    });

  auth.onAuthStateChanged(function (user) {
    if (!user || serverAuthenticated || loginInFlight) {
      return;
    }

    loginInFlight = true;
    finalizeLogin(user).catch(function (error) {
      loginInFlight = false;
      setFeedback(error.message || "Sign-in failed.");
    });
  });

  completeRedirectLogin();

  if (loginButton) {
    loginButton.addEventListener("click", function () {
      if (loginInFlight) {
        return;
      }

      setFeedback("");
      const provider = new firebase.auth.GoogleAuthProvider();
      loginInFlight = true;

      if (isLocalHost) {
        setFeedback("Redirecting to Google sign-in...");
        auth.signInWithRedirect(provider).catch(function (error) {
          loginInFlight = false;
          setFeedback(error.message || "Sign-in failed.");
        });
        return;
      }

      auth
        .signInWithPopup(provider)
        .then(function (result) {
          return finalizeLogin(result.user);
        })
        .catch(function (error) {
          if (shouldFallbackToRedirect(error)) {
            setFeedback("Popup sign-in was interrupted. Redirecting instead...");
            return auth.signInWithRedirect(provider);
          }
          throw error;
        })
        .catch(function (error) {
          loginInFlight = false;
          setFeedback(error.message || "Sign-in failed.");
        });
    });
  }

  if (logoutForm) {
    logoutForm.addEventListener("submit", function (event) {
      event.preventDefault();
      auth
        .signOut()
        .catch(function () {
          return null;
        })
        .finally(function () {
          logoutForm.submit();
        });
    });
  }

  function completeRedirectLogin() {
    auth
      .getRedirectResult()
      .then(function (result) {
        if (result && result.user) {
          loginInFlight = true;
          setFeedback("Finalizing sign-in...");
          return finalizeLogin(result.user);
        }
        return null;
      })
      .catch(function (error) {
        loginInFlight = false;
        setFeedback(error.message || "Sign-in failed.");
      });
  }

  function finalizeLogin(user) {
    if (!user) {
      loginInFlight = false;
      throw new Error("Google sign-in did not return a user.");
    }

    setFeedback("Finalizing sign-in...");
    return user
      .getIdToken()
      .then(function (token) {
        return fetch("/auth/firebase/", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: JSON.stringify({ token: token }),
        });
      })
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (payload) {
            throw new Error(payload.error || "Sign-in failed.");
          });
        }
        window.location.reload();
      })
      .finally(function () {
        loginInFlight = false;
      });
  }

  function shouldFallbackToRedirect(error) {
    const code = error && error.code ? String(error.code) : "";
    return code === "auth/popup-blocked" || code === "auth/popup-closed-by-user";
  }

  function setFeedback(message) {
    if (!feedbackNode) {
      return;
    }
    feedbackNode.textContent = message;
  }

  function getCsrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }
})();
