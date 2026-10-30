/**
 * Central translation dictionary for RAG-USTHB.
 *
 * Every user-visible string in the app lives here so that English and Arabic
 * stay in sync. Components must never branch on the language to pick a
 * hard-coded literal; they read the active dictionary via `useLang()`.
 *
 * Layout:
 *   t.common.*      generic verbs reused across screens
 *   t.nav.*         landing header, language + theme controls
 *   t.hero.*        landing hero + preview card
 *   t.features.*    landing "why us" section
 *   t.about.*       landing "about" section
 *   t.links.*       landing useful links section
 *   t.footer.*      landing footer
 *   t.auth.*        login + register pages (and the session guard screens)
 *   t.sidebar.*     chat sidebar
 *   t.chat.*        chat feed, sources and composer
 *   t.profile.*     the signed-in student's profile page
 *
 * The two languages must expose exactly the same keys. `npm run check:i18n`
 * (see `scripts/check-i18n.mjs`) asserts that, so a new string cannot be added
 * to one language and forgotten in the other.
 */

export const SUPPORTED_LANGUAGES = ['en', 'ar']
export const DEFAULT_LANGUAGE = 'en'

/**
 * Cookie that stores the chosen language.
 *
 * Defined here rather than in the provider: the provider is a `'use client'`
 * module, and constants exported from client modules become client references
 * when a Server Component imports them, which silently breaks `cookies().get()`
 * in the root layout.
 */
export const LANG_COOKIE = 'rag-lang'

/** ISO code used for `document.documentElement.lang` and `Intl` calls. */
export const LOCALE_BY_LANGUAGE = { en: 'en-US', ar: 'ar-DZ' }

export function isSupportedLanguage(value) {
  return SUPPORTED_LANGUAGES.includes(value)
}

/**
 * Decide which language to render on the server, before hydration.
 * Cookie wins, then the browser hint, then English.
 */
export function resolveInitialLanguage(cookieValue, headerLanguage) {
  if (isSupportedLanguage(cookieValue)) return cookieValue

  const hint = String(headerLanguage ?? '').toLowerCase()
  if (hint.startsWith('ar')) return 'ar'
  if (hint.startsWith('en')) return 'en'

  return DEFAULT_LANGUAGE
}

/** Replace `{name}` placeholders in a translated template string. */
export function interpolate(template, values = {}) {
  return String(template).replace(/\{(\w+)\}/g, (match, key) => (
    Object.hasOwn(values, key) ? String(values[key]) : match
  ))
}

export const translations = {
  en: {
    common: {
      language: 'Language',
      cancel: 'Cancel',
      delete: 'Delete',
    },
    nav: {
      login: 'Sign in',
      register: 'Create account',
      profile: 'Your profile',
      logout: 'Log out',
      langToggle: 'العربية',
      langLabel: 'Switch to Arabic',
      themeLight: 'Switch to light mode',
      themeDark: 'Switch to dark mode',
      mobileMenu: 'Open menu',
      closeMenu: 'Close menu',
      tagline: 'Smart Academic Assistant',
      demoBadge: 'Live demo',
    },
    hero: {
      badge: 'USTHB Student Knowledge Platform',
      title1: 'Your AI-Powered Academic Assistant at',
      titleHighlight: 'USTHB',
      description:
        'Search lectures, exam archives, and official curricula through an advanced RAG experience, delivering precise academic answers.',
      getStarted: 'Get Started Now',
      explore: 'Explore the platform now',
      documents: ['Official Lectures', 'Exam Archives', 'Official Curricula'],
      previewTitle: 'Study Assistant',
      previewSub: 'Instant academic search',
      previewQuery: 'What is the time complexity of binary search?',
      previewAnswerTitle: 'Trusted Academic Answer',
      previewAnswerText:
        'Binary search halves the search space at each step, resulting in a time complexity of',
      previewRefsTitle: 'Related Courses',
      previewRefsSub: 'Computer Science Dept',
    },
    features: {
      tag: 'Why RAG-USTHB?',
      title: 'Smarter Review & Easier Access to Curricula',
      description:
        'Interactive tools designed specifically to help Computer Science students organise their study journey and achieve top results.',
      cards: [
        {
          number: '01',
          title: 'Official Curriculum Coverage',
          description:
            'Computer Science courses and lectures at USTHB, from algorithms to databases and networks.',
          detail: 'Computer Science Dept',
        },
        {
          number: '02',
          title: 'Direct & Smart Chat',
          description:
            'Ask freely about your lessons and study topics, and get clear, accurate explanations tailored for students.',
          detail: 'Fast Academic Interaction',
        },
        {
          number: '03',
          title: 'Lectures & Exam Archives',
          description:
            'Instant and easy access to lecture content and past exam topics for effective test preparation.',
          detail: 'Verified Academic Content',
        },
      ],
    },
    about: {
      badge: 'About Platform',
      title: 'Integrated Knowledge Platform for USTHB Students',
      description:
        'RAG-USTHB combines AI with official course content, ensuring a clear and distraction-free study experience.',
      cta: 'Explore Platform Now',
      steps: [
        { step: '01', title: 'Select Subject', text: 'Choose your study courses.' },
        { step: '02', title: 'Ask Your Question', text: 'Inquire in English or Arabic.' },
        { step: '03', title: 'Get the Answer', text: 'Review accurate answers.' },
      ],
    },
    links: {
      tag: 'Selected Links',
      title: 'Useful University Resources',
      description:
        'Navigate directly to the official website, university library, or campus location.',
      items: [
        { href: 'https://www.usthb.dz', label: 'Official University Website', detail: 'News and university services' },
        { href: 'https://bu.usthb.dz', label: 'University Library', detail: 'Catalog and library services' },
        { href: 'https://www.google.com/maps/search/?api=1&query=USTHB%20Bab%20Ezzouar%20Algiers', label: 'University Map Location', detail: 'Bab Ezzouar, Algiers' },
      ],
    },
    footer: {
      left: 'RAG-USTHB · Smart Academic AI Assistant',
      right: 'University of Science and Technology Houari Boumediene',
    },
    auth: {
      eyebrow: 'RAG-USTHB · Your study portal',
      backHome: 'Back to home',
      loginTitle: 'Welcome back',
      loginDescription: 'Sign in with your university e-mail to reach your conversations.',
      registerTitle: 'Create your university account',
      registerDescription: 'Only students with an @etu.usthb.dz e-mail can join.',
      fields: {
        fullName: 'Full name',
        fullNamePlaceholder: 'e.g. Amina Benali',
        matricule: 'Matricule (student number)',
        matriculePlaceholder: 'e.g. 202312345',
        department: 'Department',
        departmentPlaceholder: 'Choose your department',
        email: 'University e-mail',
        emailPlaceholder: 'name@etu.usthb.dz',
        password: 'Password',
        passwordPlaceholder: '8 digits, e.g. 49170238',
        confirmPassword: 'Confirm password',
        confirmPasswordPlaceholder: 'Type the same 8 digits again',
      },
      departments: {
        computerScience: 'Department of Computer Science',
        mathematics: 'Department of Mathematics',
        physics: 'Department of Physics',
        chemistry: 'Department of Chemistry',
        electronics: 'Department of Electronics',
        civilEngineering: 'Department of Civil Engineering',
      },
      buttons: {
        signIn: 'Sign in',
        signUp: 'Create account',
        submitting: 'Checking…',
        showPassword: 'Show password',
        hidePassword: 'Hide password',
      },
      hints: {
        emailDomain: 'Only @etu.usthb.dz addresses can register.',
        passwordFormat: 'Your password is exactly 8 digits - no letters, spaces or symbols.',
      },
      links: {
        noAccount: 'No account yet?',
        createOne: 'Create one',
        haveAccount: 'Already have an account?',
        signIn: 'Sign in',
      },
      validation: {
        summary: 'Please correct the highlighted fields.',
        fullNameRequired: 'Enter your full name.',
        fullNameMin: 'Enter your full name using at least 2 characters.',
        matriculeRequired: 'Enter your matricule (student number).',
        departmentRequired: 'Choose your department.',
        emailRequired: 'Enter your university e-mail address.',
        emailDomain: 'Use your @etu.usthb.dz university address, e.g. name@etu.usthb.dz.',
        passwordRequired: 'Enter your password.',
        passwordFormat: 'Your password must be exactly 8 digits, for example 49170238.',
        confirmPasswordRequired: 'Repeat your password.',
        passwordMismatch: 'The two passwords do not match.',
      },
      status: {
        emailTaken: 'An account already exists for this e-mail. Sign in instead.',
        matriculeTaken: 'This matricule is already linked to an account.',
        invalidCredentials: 'Incorrect e-mail or password.',
        registered: 'Account created. You can now sign in.',
        redirecting: 'Taking you to the sign-in page…',
      },
      guard: {
        loading: 'Checking your session…',
        unavailable:
          'The account service could not be reached. Check that the backend is running, then try again.',
        retry: 'Try again',
      },
      aside: {
        logoAlt: 'University of Science and Technology Houari Boumediene logo',
        university: 'University of Science and Technology Houari Boumediene',
        badge: 'A study space for university students',
        title: 'Make your revision time more focused and clearer.',
        description:
          'Explore course content, review key concepts, and move between answers backed by academic sources.',
        rulesTitle: 'What you need to sign up',
        rule1: 'A university e-mail ending in @etu.usthb.dz',
        rule2: 'A password of exactly 8 digits',
      },
      footer: 'University education, in a language closer to you',
    },
    sidebar: {
      asideLabel: 'Your conversations',
      closeOverlay: 'Close the sidebar menu',
      closeMenu: 'Close menu',
      brandTagline: 'Your smart study assistant',
      newConversation: 'New conversation',
      conversationsTitle: 'Your conversations',
      conversationCount: '{count} conversations',
      searchLabel: 'Search your conversations',
      searchPlaceholder: 'Search your conversations…',
      loading: 'Loading your conversations…',
      emptyConversations: 'No conversations match your search.',
      untitled: 'New conversation',
      messageCount: '{count} messages',
      sortNewest: 'Newest first',
      sortOldest: 'Oldest first',
      error: 'Your conversations could not be loaded.',
      retry: 'Try again',
      footer: 'University of Science and Technology Houari Boumediene',
    },
    chat: {
      homeButton: 'Home',
      homeTitle: 'Back to the home page',
      menuButton: 'Open the sidebar',
      profileButton: 'Your profile',
      logoutButton: 'Log out',
      feedLabel: 'Conversation',
      emptyTitle: 'Ask your first question',
      emptyText:
        'Ask a question about your courses. The answer is built from the passages retrieved in the indexed university documents.',
      roleUser: 'You',
      roleAssistant: 'RAG Assistant',
      thinking: 'Searching the indexed documents…',
      sourcesTitle: 'Sources',
      sourceScore: 'Match {score}',
      sourcePage: 'page {page}',
      noEvidence:
        'I could not find anything relevant to that question in the indexed documents. Try rephrasing it, or ask about a topic that is covered by the indexed courses.',
      noSources: 'No passage was relevant enough to cite.',
      errorMessage: 'Something went wrong while answering.',
      errorNetwork: 'The server could not be reached. Check that the backend is running.',
      retry: 'Try again',
      composerLabel: 'Type your question',
      composerPlaceholder: 'Type your question about your courses…',
      composerHint: 'Answers are built from the passages retrieved in the indexed university documents.',
      sendLabel: 'Send the question',
      sending: 'Sending…',
      newChat: 'New conversation',
      deleteConversation: 'Delete this conversation',
      deleteConfirm: 'Delete this conversation? Its messages cannot be recovered.',
    },
    profile: {
      title: 'Your profile',
      subtitle: 'The details your university account was registered with.',
      backToChat: 'Back to the chatbot',
      logout: 'Log out',
      fullName: 'Full name',
      matricule: 'Matricule',
      department: 'Department',
      email: 'University e-mail',
      loading: 'Loading your profile…',
      unavailable: 'Your profile could not be loaded.',
      retry: 'Try again',
      signedOut: 'You have been signed out.',
    },
  },

  ar: {
    common: {
      language: 'اللغة',
      cancel: 'إلغاء',
      delete: 'حذف',
    },
    nav: {
      login: 'تسجيل الدخول',
      register: 'إنشاء حساب',
      profile: 'ملفك الشخصي',
      logout: 'تسجيل الخروج',
      langToggle: 'English',
      langLabel: 'التبديل إلى الإنجليزية',
      themeLight: 'تفعيل الوضع الفاتح',
      themeDark: 'تفعيل الوضع الداكن',
      mobileMenu: 'فتح القائمة',
      closeMenu: 'إغلاق القائمة',
      tagline: 'مساعدك الأكاديمي الذكي',
      demoBadge: 'مثال توضيحي',
    },
    hero: {
      badge: 'منصة المعرفة لطلاب USTHB',
      title1: 'مساعدك الأكاديمي الذكي المدعوم بالذكاء الاصطناعي في',
      titleHighlight: 'USTHB',
      description:
        'ابحث في المحاضرات، أرشيف الامتحانات والمناهج الرسمية عبر تجربة ذكية للاسترجاع المعزز بالتوليد، لإجابات دقيقة ومباشرة.',
      getStarted: 'ابدأ الآن',
      explore: 'استكشف المزايا',
      documents: ['المحاضرات الرسمية', 'أرشيف الامتحانات', 'المناهج والمقررات'],
      previewTitle: 'مساعد المواد الدراسية',
      previewSub: 'استفسار أكاديمي فوري',
      previewQuery: 'ما هو التعقيد الزمني لخوارزمية البحث الثنائي؟',
      previewAnswerTitle: 'إجابة أكاديمية موثوقة',
      previewAnswerText:
        'يعمل البحث الثنائي على تقليص مجال البحث إلى النصف في كل خطوة، لذلك يكون تعقيده الزمني',
      previewRefsTitle: 'المقررات المرتبطة',
      previewRefsSub: 'قسم الإعلام الآلي',
    },
    features: {
      tag: 'لماذا RAG-USTHB؟',
      title: 'مراجعة أذكى ومقررات أسهل للوصول',
      description:
        'أدوات تفاعلية صُممت خصيصاً لمساعدة طلاب كلية الإعلام الآلي في تنظيم رحلة المراجعة وتحصيل أفضل النتائج.',
      cards: [
        {
          number: '01',
          title: 'تغطية شاملة للمناهج الرسمية',
          description:
            'مقررات ومحاضرات علوم الحاسوب والإعلام الآلي في USTHB، من الخوارزميات وهياكل البيانات إلى قواعد البيانات والشبكات.',
          detail: 'مقررات قسم الإعلام الآلي',
        },
        {
          number: '02',
          title: 'دردشة ذكية ومباشرة',
          description:
            'اسأل واستفسر بحرية عن دروسك ومواضيعك الدراسية، واحصل على شروحات واضحة ودقيقة مصممة خصيصاً للطلاب.',
          detail: 'تفاعل أكاديمي سريع',
        },
        {
          number: '03',
          title: 'أرشيف المحاضرات والامتحانات',
          description:
            'وصول فوري وسهل إلى محتوى المحاضرات وامتحانات السنوات السابقة لمراجعة شاملة وفعالة قبل الامتحانات.',
          detail: 'محتوى أكاديمي موثوق',
        },
      ],
    },
    about: {
      badge: 'عن المنصة',
      title: 'منصة معرفية متكاملة لطلاب USTHB',
      description:
        'يجمع RAG-USTHB بين قوة الذكاء الاصطناعي ومحتوى المقررات الرسمية، لتستمتع بتجربة دراسية واضحة وخالية من التشتت.',
      cta: 'استكشف المنصة الآن',
      steps: [
        { step: '01', title: 'اختر المادة', text: 'حدد مقرراتك الدراسية.' },
        { step: '02', title: 'اطرح سؤالك', text: 'استفسر بالعربية أو الإنجليزية.' },
        { step: '03', title: 'احصل على الإجابة', text: 'راجع إجابات دقيقة وموثوقة.' },
      ],
    },
    links: {
      tag: 'روابط مختارة',
      title: 'موارد جامعية مفيدة',
      description: 'انتقل مباشرة إلى الموقع الرسمي، مكتبة الجامعة، أو موقع الحرم الجامعي.',
      items: [
        { href: 'https://www.usthb.dz', label: 'الموقع الرسمي للجامعة', detail: 'الأخبار والخدمات الجامعية' },
        { href: 'https://bu.usthb.dz', label: 'المكتبة الجامعية', detail: 'الفهرس والخدمات المكتبية' },
        { href: 'https://www.google.com/maps/search/?api=1&query=USTHB%20Bab%20Ezzouar%20Algiers', label: 'موقع الجامعة على الخريطة', detail: 'باب الزوار، الجزائر العاصمة' },
      ],
    },
    footer: {
      left: 'RAG-USTHB · مساعدك الأكاديمي الذكي',
      right: 'جامعة العلوم والتكنولوجيا هواري بومدين',
    },
    auth: {
      eyebrow: 'RAG-USTHB · بوابتك الدراسية',
      backHome: 'العودة إلى الرئيسية',
      loginTitle: 'مرحباً بعودتك',
      loginDescription: 'سجّل الدخول ببريدك الجامعي للوصول إلى محادثاتك.',
      registerTitle: 'أنشئ حسابك الجامعي',
      registerDescription: 'يمكن للطلاب الحاملين لبريد @etu.usthb.dz فقط الانضمام.',
      fields: {
        fullName: 'الاسم الكامل',
        fullNamePlaceholder: 'مثال: أمينة بن علي',
        matricule: 'رقم الطالب (Matricule)',
        matriculePlaceholder: 'مثال: 202312345',
        department: 'القسم',
        departmentPlaceholder: 'اختر قسمك',
        email: 'البريد الجامعي',
        emailPlaceholder: 'name@etu.usthb.dz',
        password: 'كلمة المرور',
        passwordPlaceholder: 'ثمانية أرقام، مثال: 49170238',
        confirmPassword: 'تأكيد كلمة المرور',
        confirmPasswordPlaceholder: 'أعد إدخال الأرقام الثمانية نفسها',
      },
      departments: {
        computerScience: 'قسم الإعلام الآلي',
        mathematics: 'قسم الرياضيات',
        physics: 'قسم الفيزياء',
        chemistry: 'قسم الكيمياء',
        electronics: 'قسم الإلكترونيات',
        civilEngineering: 'قسم الهندسة المدنية',
      },
      buttons: {
        signIn: 'تسجيل الدخول',
        signUp: 'إنشاء الحساب',
        submitting: 'جارٍ التحقق…',
        showPassword: 'إظهار كلمة المرور',
        hidePassword: 'إخفاء كلمة المرور',
      },
      hints: {
        emailDomain: 'يمكن التسجيل بعنوان @etu.usthb.dz فقط.',
        passwordFormat: 'تتكوّن كلمة مرورك من ثمانية أرقام فقط، دون حروف أو مسافات أو رموز.',
      },
      links: {
        noAccount: 'ليس لديك حساب؟',
        createOne: 'أنشئ حساباً',
        haveAccount: 'لديك حساب بالفعل؟',
        signIn: 'تسجيل الدخول',
      },
      validation: {
        summary: 'يرجى تصحيح الحقول المحددة أدناه.',
        fullNameRequired: 'أدخل اسمك الكامل.',
        fullNameMin: 'أدخل اسمك الكامل بحرفين على الأقل.',
        matriculeRequired: 'أدخل رقم الطالب (Matricule).',
        departmentRequired: 'اختر قسمك.',
        emailRequired: 'أدخل بريدك الجامعي.',
        emailDomain: 'استخدم عنوانك الجامعي @etu.usthb.dz، مثال: name@etu.usthb.dz.',
        passwordRequired: 'أدخل كلمة المرور.',
        passwordFormat: 'يجب أن تتكون كلمة المرور من ثمانية أرقام بالضبط، مثال: 49170238.',
        confirmPasswordRequired: 'أعد إدخال كلمة المرور.',
        passwordMismatch: 'كلمتا المرور غير متطابقتين.',
      },
      status: {
        emailTaken: 'يوجد حساب مسجّل بهذا البريد بالفعل. سجّل الدخول بدلاً من ذلك.',
        matriculeTaken: 'رقم الطالب هذا مرتبط بحساب موجود.',
        invalidCredentials: 'البريد الإلكتروني أو كلمة المرور غير صحيحة.',
        registered: 'تم إنشاء حسابك. يمكنك الآن تسجيل الدخول.',
        redirecting: 'جارٍ تحويلك إلى صفحة تسجيل الدخول…',
      },
      guard: {
        loading: 'جارٍ التحقق من جلستك…',
        unavailable: 'تعذر الوصول إلى خدمة الحسابات. تأكد من تشغيل الخادم ثم حاول مرة أخرى.',
        retry: 'إعادة المحاولة',
      },
      aside: {
        logoAlt: 'شعار جامعة العلوم والتكنولوجيا هواري بومدين',
        university: 'جامعة العلوم والتكنولوجيا هواري بومدين',
        badge: 'مساحة دراسية لطلاب الجامعة',
        title: 'اجعل وقت المراجعة أكثر تركيزاً ووضوحاً.',
        description:
          'اكتشف محتوى المقررات، راجع المفاهيم الأساسية، وتنقّل بين إجابات مدعومة بمراجع دراسية.',
        rulesTitle: 'ما تحتاجه لإنشاء حساب',
        rule1: 'بريد جامعي ينتهي بـ @etu.usthb.dz',
        rule2: 'كلمة مرور مكوّنة من ثمانية أرقام',
      },
      footer: 'تعليم جامعي، بلغة أقرب إليك',
    },
    sidebar: {
      asideLabel: 'قائمة محادثاتك',
      closeOverlay: 'إغلاق القائمة الجانبية',
      closeMenu: 'إغلاق القائمة',
      brandTagline: 'مساعدك الدراسي الذكي',
      newConversation: 'محادثة جديدة',
      conversationsTitle: 'محادثاتك',
      conversationCount: '{count} محادثات',
      searchLabel: 'ابحث في محادثاتك',
      searchPlaceholder: 'ابحث في محادثاتك...',
      loading: 'جارٍ تحميل محادثاتك...',
      emptyConversations: 'لا توجد محادثات مطابقة للبحث.',
      untitled: 'محادثة جديدة',
      messageCount: '{count} رسائل',
      sortNewest: 'الأحدث أولاً',
      sortOldest: 'الأقدم أولاً',
      error: 'تعذر تحميل محادثاتك.',
      retry: 'إعادة المحاولة',
      footer: 'جامعة العلوم والتكنولوجيا هواري بومدين',
    },
    chat: {
      homeButton: 'الرئيسية',
      homeTitle: 'العودة إلى الصفحة الرئيسية',
      menuButton: 'فتح القائمة الجانبية',
      profileButton: 'ملفك الشخصي',
      logoutButton: 'تسجيل الخروج',
      feedLabel: 'المحادثة',
      emptyTitle: 'اطرح أول سؤال',
      emptyText:
        'اطرح سؤالاً حول موادك. تُبنى الإجابة من المقاطع المسترجعة من المستندات الجامعية المرقمنة.',
      roleUser: 'أنت',
      roleAssistant: 'مساعد RAG',
      thinking: 'جارٍ البحث في المستندات المرقمنة...',
      sourcesTitle: 'المصادر',
      sourceScore: 'تطابق {score}',
      sourcePage: 'صفحة {page}',
      noEvidence:
        'لم أجد ما يرتبط بسؤالك في المستندات المرقمنة. حاول صياغته بطريقة أخرى، أو اسأل عن موضوع تغطيه الدورات المرقمنة.',
      noSources: 'لم يكن أي مقطع ذا صلة كافية ليُستشهد به.',
      errorMessage: 'حدث خطأ أثناء إعداد الإجابة.',
      errorNetwork: 'تعذر الوصول إلى الخادم. تأكد من تشغيل الخادم الخلفي.',
      retry: 'إعادة المحاولة',
      composerLabel: 'اكتب سؤالك',
      composerPlaceholder: 'اكتب سؤالك حول موادك...',
      composerHint: 'تُبنى الإجابات من المقاطع المسترجعة من المستندات الجامعية المرقمنة.',
      sendLabel: 'إرسال السؤال',
      sending: 'جارٍ الإرسال...',
      newChat: 'محادثة جديدة',
      deleteConversation: 'حذف هذه المحادثة',
      deleteConfirm: 'هل تريد حذف هذه المحادثة؟ لا يمكن استرجاع رسائلها.',
    },
    profile: {
      title: 'ملفك الشخصي',
      subtitle: 'البيانات التي سُجّل بها حسابك الجامعي.',
      backToChat: 'العودة إلى المساعد',
      logout: 'تسجيل الخروج',
      fullName: 'الاسم الكامل',
      matricule: 'رقم الطالب',
      department: 'القسم',
      email: 'البريد الجامعي',
      loading: 'جارٍ تحميل ملفك الشخصي...',
      unavailable: 'تعذر تحميل ملفك الشخصي.',
      retry: 'إعادة المحاولة',
      signedOut: 'تم تسجيل خروجك.',
    },
  },
}

/** Guard so a missing key degrades to English instead of crashing the UI. */
export function getDictionary(language) {
  return translations[language] ?? translations[DEFAULT_LANGUAGE]
}
