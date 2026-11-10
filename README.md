# WhatsApp Auto Responder — Android companion + AI gateway prototype

Android companion app-টি notification থেকে message পড়ে, বাছাই করা knowledge base ও ঐচ্ছিক Generative AI backend দিয়ে reply তৈরি করার চেষ্টা করে। এটি পরীক্ষামূলক; production-ready বা WhatsApp-এর official integration নয়।

## ফিচার

- WhatsApp (`com.whatsapp`) ও WhatsApp Business (`com.whatsapp.w4b`) app package নির্বাচন, master auto-reply switch এবং sender Allow/Deny rule CRUD ও Allowlist mode।
- UI-তে knowledge entry add/edit/delete এবং JSON import। নমুনা: `knowledge_base.example.json`।
- **Local mode:** internet/API ছাড়াই local TF-IDF শব্দ-মিল; মিল না পেলে reply নয়।
- **Generative AI mode:** Android app HTTPS-এ নিজের backend-এ request পাঠায়। Backend OpenAI Responses API-তে message, সাম্প্রতিক conversation এবং knowledge base পাঠিয়ে উত্তর তৈরি করে। Model-এর কাছে অপ্রাসঙ্গিক/অপর্যাপ্ত knowledge হলে `[NO_REPLY]` ফেরত দিতে বলা হয়। ৩০টি বা কম knowledge entry হলে সবগুলো context হিসেবে যায়; ৩০টির বেশি হলে app স্থানীয় lexical matcher দিয়ে সেরা ৩০টি বেছে নেয়।
- WhatsApp notification-এ inline reply action পাওয়া গেলেই উত্তর পাঠানোর চেষ্টা হয়। Android Notification Access ব্যবহারকারীকে নিজে অনুমতি দিতে হবে।

## Generative AI backend চালানো

OpenAI API key **কখনো Android app বা Git-এ রাখবেন না**. Backend-এ OpenAI key server environment secret হিসেবে থাকে; Android-এ আলাদা backend access token বসে। ChatGPT Plus সাবস্ক্রিপশন API usage-এর খরচ অন্তর্ভুক্ত করে না—API billing আলাদা।

1. Python 3.12 ও Docker ব্যবহার করুন। `backend/.env.example` কপি করে `backend/.env` বানান এবং server-এ secret হিসেবে সেট করুন:
   - `OPENAI_API_KEY` — OpenAI API key
   - `OPENAI_MODEL` — ডিফল্ট `gpt-4.1-mini`
   - `APP_ACCESS_TOKEN` — শক্তিশালী random token (উদাহরণ: `openssl rand -hex 32`)
   - ঐচ্ছিক `REQUESTS_PER_MINUTE` — IP-প্রতি rate limit, ডিফল্ট ২০
2. Project root থেকে চালান:

   ```bash
   docker build -t wa-auto-responder-ai ./backend
   docker run --rm --env-file backend/.env -p 8000:8000 wa-auto-responder-ai
   ```

3. Android app-এ **Generative AI** চালু করে backend-এর **HTTPS root URL** (যেমন `https://your-host.example`) ও একই `APP_ACCESS_TOKEN` লিখে **AI সেটিংস সংরক্ষণ** করুন। Public deployment-এ TLS/HTTPS বাধ্যতামূলক; Android client HTTP গ্রহণ করে না। `/health` endpoint দিয়ে backend health পরীক্ষা করা যায়।
4. OpenAI usage, rate limits ও hosting bill পর্যবেক্ষণ করুন। Test-এর জন্য প্রথমে অল্প কয়েকটি knowledge entry ও নিজের chat ব্যবহার করুন।

Local mode ব্যবহার করতে Generative AI switch বন্ধ রাখুন। AI mode-এ backend unavailable, token ভুল বা knowledge খালি থাকলে local fallback হবে না—অ্যাপ নীরব থাকবে।

## Android app তৈরি ও সেটআপ

1. Android Studio, JDK 17, Android SDK 35, Gradle 8.9 (AGP 8.7.3) ব্যবহার করুন। এই checkout-এ Gradle wrapper নেই; local Gradle দিয়ে project sync/build করুন, অথবা `gradle wrapper --gradle-version 8.9` project root-এ চালিয়ে wrapper তৈরি করে Android Studio-তে project খুলুন, Gradle sync করুন, তারপর `app` configuration চালান।
2. ফোনে অ্যাপ install করে **নোটিফিকেশন অ্যাক্সেস সেট করুন** চাপুন এবং Android Settings-এ Notification Access অনুমোদন করুন।
3. কোন WhatsApp app থেকে কাজ করবে বাছুন; sender Allow/Deny rules ও knowledge base সেট করুন। অটো-রিপ্লে শুরুতে বন্ধ থাকে।
4. Generative AI ব্যবহার করলে backend URL/token save করুন; তারপর AI switch ও master auto-reply switch চালু করুন। প্রথমে পরীক্ষামূলক chat-এ পরীক্ষা করুন।

## ডেটা, privacy ও নিরাপত্তা

- AI mode-এ **প্রতিটি অনুমোদিত incoming message**, সর্বশেষ ৮টি conversation turn পর্যন্ত, এবং সর্বোচ্চ ৩০টি knowledge entry OpenAI API-তে যায়। Sender-এর নাম/ফোন নম্বর পাঠানো হয় না। AI উত্তর আসার পর app-এ per-contact recent context স্থানীয়ভাবে থাকে (সর্বোচ্চ ১০০টি thread); Notification Access-ও সংবেদনশীল অনুমতি। Generative AI switch বন্ধ রাখলে কোনো network call হয় না।
- OpenAI API key শুধু backend environment-এ থাকে। Backend access token Android-এর app-private preferences-এ রাখা হয়—এটি API key নয়, তবে rooted/compromised ফোনে token বের হতে পারে। Token Git-এ দেবেন না; public APK বিতরণের আগে shared-token auth-এর বদলে per-user/per-device authentication, TLS termination, persistent rate limiting এবং usage quotas যোগ করুন। বর্তমান in-memory rate limit restart হলে reset হয়।
- Backend prompt message/knowledge/history-কে untrusted data ধরে; model-কে knowledge-ভিত্তিক উত্তর দিতে ও যথেষ্ট তথ্য না থাকলে নীরব থাকতে নির্দেশ দেওয়া হয়। Generative AI তবুও ভুল উত্তর দিতে পারে; গুরুত্বপূর্ণ তথ্য নিজে যাচাই করুন।
- WhatsApp notification-এ sender/message যেমন আসে তার ওপরই নিয়ম চলে; group, media, hidden notification বা WhatsApp/Android update-এ আচরণ বদলাতে পারে। Reply action না থাকলে উত্তর যাবে না।
- একই WhatsApp app-এর ভেতরের একাধিক account আলাদাভাবে শনাক্ত করার নিশ্চয়তা নেই; শুধু WhatsApp বনাম WhatsApp Business package নির্বাচন হয়। Cloned/third-party apps সমর্থিত নয়।
- ব্যক্তিগত WhatsApp call auto-answer/decline এই prototype-এ বাস্তবায়িত নয়। Notification action/API ফোনভেদে অনির্ভরযোগ্য; কোনো কল ধরবে বা কাটবে না।

## যাচাই

Backend test চালাতে আগে `python -m pip install -r backend/requirements.txt`, তারপর `python -m unittest discover -s backend/tests` চালান। Android build/device test-এর জন্য Android Studio, JDK ও SDK প্রয়োজন।
