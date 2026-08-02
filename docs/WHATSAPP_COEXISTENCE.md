# WhatsApp Coexistence в Revora

Этот документ описывает только подключение существующего номера из приложения
WhatsApp Business с сохранением приложения и истории чатов.

## Что возвращает Meta

Для Coexistence успешное завершение Embedded Signup возвращает два независимых
сигнала в исходное окно:

- одноразовый `code` в callback `FB.login`;
- событие `WA_EMBEDDED_SIGNUP` с типом
  `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` и `waba_id`.

В событии Coexistence может отсутствовать `phone_number_id`. В этом случае backend
Revora получает список номеров WABA через Graph API и выбирает единственный номер.

## Последовательность подключения

1. Frontend запускает Facebook Login for Business с конфигурацией Embedded Signup.
2. Владелец номера выбирает подключение существующего WhatsApp Business App.
3. Meta возвращает `code` и `waba_id`.
4. Backend обменивает `code` на business integration system user token.
5. Backend получает `phone_number_id` через `/<WABA_ID>/phone_numbers`.
6. Backend подписывает приложение на WABA через `/<WABA_ID>/subscribed_apps`.
7. Для Coexistence шаг регистрации номера пропускается: номер уже зарегистрирован.
8. Backend сразу запускает `smb_app_state_sync` и `history` через SMB App Data API.
9. Токен хранится в базе только в зашифрованном виде, канал остаётся в режиме
   `draft` до отдельного включения автоматической отправки.

## Обязательные настройки Meta

В **Facebook Login for Business → Settings** должны быть включены:

- Client OAuth Login;
- Web OAuth Login;
- Enforce HTTPS;
- Embedded Browser OAuth Login;
- Strict Mode for Redirect URIs;
- Login with the JavaScript SDK.

В Allowed Domains и Valid OAuth Redirect URIs должен быть указан HTTPS-адрес
страницы, с которой запускается Embedded Signup:

`https://revora-web-bekarysibrashev.onrender.com/whatsapp/`

Конфигурация должна использовать Embedded Signup v4 и продукт WhatsApp Cloud API.

## Webhooks

Callback:

`https://revora-api-bekarysibrashev.onrender.com/api/v1/webhooks/whatsapp`

Приложение должно быть подписано как минимум на поля:

- `messages`;
- `account_update`;
- `history`;
- `smb_app_state_sync`;
- `smb_message_echoes`.

Revora импортирует `history` без запуска ИИ на старых сообщениях. Новые входящие
`messages` создают диалог и черновик ответа. `smb_message_echoes` сохраняет сообщения,
которые сотрудники отправили из приложения WhatsApp Business.

## Требования Meta

- WhatsApp Business App версии 2.24.17 или новее;
- приложение разработчика принадлежит Solution Partner или Tech Provider;
- подтверждённая компания и Advanced Access к
  `whatsapp_business_management` и `whatsapp_business_messaging`;
- работающий HTTPS webhook;
- синхронизация истории запускается не позднее 24 часов после onboarding.

До выполнения этих требований нельзя подключать рабочий номер клиники.

