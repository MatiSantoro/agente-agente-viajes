(() => {
  const config = window.TRAVEL_UI_CONFIG;
  const form = document.querySelector('#login-form');
  const username = document.querySelector('#username');
  const password = document.querySelector('#password');
  const status = document.querySelector('#login-status');
  const submit = document.querySelector('#sign-in');
  const toggle = document.querySelector('#password-toggle');

  toggle.addEventListener('click', () => {
    const visible = password.type === 'text';
    password.type = visible ? 'password' : 'text';
    toggle.textContent = visible ? 'Show' : 'Hide';
    toggle.setAttribute('aria-label', visible ? 'Show password' : 'Hide password');
    password.focus();
  });

  function message(text, pending = false) {
    status.textContent = text;
    status.classList.toggle('pending', pending);
  }

  async function signIn(event) {
    event.preventDefault();
    if (!form.reportValidity()) return;
    message('Creating your private session…', true);
    submit.disabled = true;
    try {
      const response = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-amz-json-1.1',
          'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
        },
        body: JSON.stringify({
          AuthFlow: 'USER_PASSWORD_AUTH',
          ClientId: config.userPoolClientId,
          AuthParameters: { USERNAME: username.value.trim(), PASSWORD: password.value },
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.AuthenticationResult?.AccessToken) {
        throw new Error(data.message || 'Check your username and password, then try again.');
      }
      window.travelUi.store.setItem('access-token', data.AuthenticationResult.AccessToken);
      password.value = '';
      window.travelUi.openApp();
    } catch (error) {
      message(error.message || 'We could not sign you in. Please try again.');
      password.focus();
    } finally {
      submit.disabled = false;
    }
  }

  form.addEventListener('submit', signIn);
})();
