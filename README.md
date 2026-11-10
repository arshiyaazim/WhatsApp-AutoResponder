# WhatsApp Auto Responder — Android companion prototype

এই repository-টি পুরোনো Python 2/WhatsApp Web bot থেকে Android companion-app prototype-এ রূপান্তর করা হচ্ছে। Android অ্যাপটি ফোনে আলাদাভাবে ইনস্টল করতে হবে; WhatsApp-এর কোনো APK পরিবর্তন বা account login/session চুরি করে না। **এটি এখনো পরীক্ষামূলক, production-ready নয়।**

## কী আছে

- অটো-রিপ্লে এবং প্রতিটি সমর্থিত WhatsApp অ্যাপের জন্য আলাদা on/off নির্বাচন। বর্তমানে WhatsApp (`com.whatsapp`) ও WhatsApp Business (`com.whatsapp.w4b`) শনাক্ত করা হয়।
- contact/name/number rule যোগ, edit, delete; Allowlist mode এবং deny-first নীতি।
- UI থেকে knowledge entry যোগ, edit, delete; JSON knowledge base ইমপোর্ট।
- স্থানীয় TF-IDF/cosine lexical retrieval দিয়ে knowledge base থেকে উত্তর বাছাই। উত্তর না মিললে চুপ থাকে। কোনো message বা knowledge বাইরের server-এ পাঠানো হয় না।
- WhatsApp-এর notification-এ inline reply action থাকলে সেটি ব্যবহার করে উত্তর পাঠানোর চেষ্টা। Android Notification Access ব্যবহারকারীকে নিজে Settings-এ গিয়ে অনুমোদন করতে হবে।

`knowledge_base.example.json` থেকে নমুনা JSON ইমপোর্ট করা যায়। ফাইলের ধরন:

```json
[
  {"question": "দোকান কখন খোলা?", "answer": "সকাল ৯টা থেকে বিকেল ৫টা।", "keywords": "সময়, খোলার সময়"}
]
```

## চালানো

1. Android Studio, JDK 17, Android SDK 35 এবং Gradle 8.9 ব্যবহার করুন (AGP 8.7.3)। এই checkout-এ Gradle wrapper নেই; local Gradle দিয়ে project sync/build করুন, অথবা project root-এ `gradle wrapper --gradle-version 8.9` চালিয়ে wrapper তৈরি করুন। তারপর Android Studio-তে project খুলে `app` configuration চালান।
2. Android ফোনে অ্যাপ ইনস্টল করুন। **নোটিফিকেশন অ্যাক্সেস** বাটনে চাপ দিয়ে Android Settings থেকে এই অ্যাপকে অনুমতি দিন।
3. কোন WhatsApp ইনস্টলেশন চলবে, অটো-রিপ্লে, contact rules এবং knowledge base সেট করুন। প্রথমে নিজের/পরীক্ষামূলক chat-এ পরীক্ষা করুন।
4. অটো-রিপ্লে চালু করার পর Android ব্যাটারি/ব্যাকগ্রাউন্ড সীমাবদ্ধতায় notification service থেমে যেতে পারে; নির্মাতা-নির্দিষ্ট battery optimization আচরণও পরীক্ষা করুন।

## বাস্তবায়নের সীমা ও নিরাপত্তা

- **একই WhatsApp অ্যাপের ভিতরের একাধিক account:** Android notification সাধারণত কোন account/profile-এ message এসেছে তা নির্ভরযোগ্যভাবে দেয় না। এই prototype অ্যাপ-প্যাকেজ (WhatsApp বনাম WhatsApp Business) নির্বাচন করে; একই package-এর account-গুলোর মধ্যে নিশ্চিতভাবে বাছাই করতে পারে না। Dual-app/cloned/third-party WhatsApp installation সমর্থিত নয়।
- **নোটিফিকেশন-নির্ভর:** sender নাম/নম্বর ও message text notification-এ যেমন পাওয়া যায়, তার ওপরই নিয়ম চলে। লুকানো/সংক্ষিপ্ত/ভিন্ন ভাষার notification, media, group notification এবং WhatsApp-এর ভবিষ্যৎ পরিবর্তনে কাজ নাও করতে পারে। নম্বর না দেখালে নম্বর-ভিত্তিক rule মিলবে না—সেক্ষেত্রে notification-এ থাকা নাম দিয়ে rule দিন।
- **রিপ্লে পাঠানো নিশ্চিত নয়:** Android/WhatsApp reply action না দিলে, notification বন্ধ/মেয়াদোত্তীর্ণ হলে বা OS আটকালে কোনো উত্তর যাবে না। কোনো UI automation/accessibility workaround ব্যবহার করা হয়নি।
- **Knowledge base এখন LLM নয়:** স্থানীয় TF-IDF মূলত শব্দের মিল ধরে; প্রকৃত semantic understanding, conversation history, generative AI, hallucination guard বা ভাষাভিত্তিক embedding নেই। এগুলো চাইলে ভবিষ্যতে ঐচ্ছিক/স্ব-হোস্টেড AI backend যোগ করা যাবে—তখন message বাইরের মডেলে পাঠানোর আগে consent ও privacy policy প্রয়োজন।
- **WhatsApp কল auto-accept/decline:** ব্যক্তিগত WhatsApp app-এর কল নিয়ন্ত্রণে এই ব্যবহারের জন্য supported public API নেই। Android notification-এ কোনো সংস্করণে call action দেখা যেতে পারে, কিন্তু WhatsApp/Android তা third-party app-কে সবসময় expose করবে বা action চালাতে দেবে—এমন নিশ্চয়তা নেই। WhatsApp Business Platform-এর business calling আলাদা service; সেটি ফোনে থাকা personal account নিয়ন্ত্রণের API নয়। তাই prototype-এ কল স্বয়ংক্রিয়ভাবে ধরা/কাটা **বাস্তবায়িত নয়**। Accessibility দিয়ে UI tap করানো ভঙ্গুর, device/WhatsApp সংস্করণনির্ভর এবং নিরাপদ/নির্ভরযোগ্য সমাধান হিসেবে উপস্থাপন করা যাবে না।
- Notification Access সংবেদনশীল অনুমতি। message text স্থানীয় knowledge lookup ও inline reply-এর জন্য প্রক্রিয়া হয়; raw message log বা cloud upload নেই। duplicate reply ঠেকাতে message-ভিত্তিক hash ও timestamp local preferences-এ রাখা হয়। তবু আলাদা পরীক্ষামূলক ফোনে ব্যবহার করুন।

## বর্তমান repository

পুরোনো Python 2/Selenium WhatsApp Web bot অচল selector ও obsolete dependency-র ওপর নির্ভর করত, তাই Android prototype-এ বিভ্রান্তি না ঘটাতে তা সরানো হয়েছে। এই branch-এ করা পরিবর্তন বর্তমান remote-এ স্বয়ংক্রিয়ভাবে push করা হয়নি। আলাদা GitHub repository-তে প্রকাশ করতে হলে destination repository-র নাম ও public/private পছন্দ জানাতে হবে।
