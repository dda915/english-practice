"""初期データ投入スクリプト"""
from .database import engine, SessionLocal, Base
from .models import Question, Child, Setting


DUMMY_QUESTIONS = [
    (1, "私は毎朝6時に起きます。", "I get up at six every morning."),
    (2, "彼女は英語がとても上手です。", "She is very good at English."),
    (3, "この本は面白いですか？", "Is this book interesting?"),
    (4, "昨日、友達と映画を見ました。", "I watched a movie with my friend yesterday."),
    (5, "あなたは何時に学校に行きますか？", "What time do you go to school?"),
    (6, "私たちは公園でサッカーをしました。", "We played soccer in the park."),
    (7, "彼は来週、東京に行く予定です。", "He is going to go to Tokyo next week."),
    (8, "この部屋には机が3つあります。", "There are three desks in this room."),
    (9, "母は今、料理をしています。", "My mother is cooking now."),
    (10, "私は将来、医者になりたいです。", "I want to be a doctor in the future."),
    (11, "彼女は昨年アメリカに住んでいました。", "She lived in America last year."),
    (12, "あなたはどんな音楽が好きですか？", "What kind of music do you like?"),
    (13, "この問題は私には難しすぎます。", "This question is too difficult for me."),
    (14, "雨が降り始めたので、家に帰りました。", "I went home because it started to rain."),
    (15, "彼はクラスで一番背が高いです。", "He is the tallest in his class."),
    (16, "もし明日晴れたら、ピクニックに行きましょう。", "If it is sunny tomorrow, let's go on a picnic."),
    (17, "この町には古い寺がたくさんあります。", "There are many old temples in this town."),
    (18, "彼女は毎日30分ピアノを練習します。", "She practices the piano for thirty minutes every day."),
    (19, "私はまだ宿題を終えていません。", "I have not finished my homework yet."),
    (20, "あなたは今まで外国に行ったことがありますか？", "Have you ever been to a foreign country?"),
    (21, "彼に電話してくれませんか？", "Could you call him, please?"),
    (22, "この写真を見てください。", "Please look at this picture."),
    (23, "私たちはお互いを助け合うべきです。", "We should help each other."),
    (24, "父は私に新しい自転車を買ってくれました。", "My father bought me a new bicycle."),
    (25, "彼女がいつ来るか知っていますか？", "Do you know when she will come?"),
    (26, "その知らせを聞いて驚きました。", "I was surprised to hear the news."),
    (27, "窓を開けてもいいですか？", "May I open the window?"),
    (28, "京都は美しい街として知られています。", "Kyoto is known as a beautiful city."),
    (29, "彼は何も言わずに部屋を出ました。", "He left the room without saying anything."),
    (30, "英語を話すことは大切です。", "It is important to speak English."),
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 問題がなければ投入
        if db.query(Question).count() == 0:
            for num, jp, en in DUMMY_QUESTIONS:
                db.add(Question(number=num, japanese=jp, english=en))
            print(f"問題 {len(DUMMY_QUESTIONS)} 問を投入しました")

        # 子供がいなければ作成
        if db.query(Child).count() == 0:
            for name in ["子供A", "子供B", "子供C"]:
                db.add(Child(name=name))
            print("子供3人を作成しました")

        # デフォルト設定
        if not db.query(Setting).get("exchange_rate_money"):
            db.add(Setting(key="exchange_rate_money", value="10"))
        if not db.query(Setting).get("exchange_rate_phone"):
            db.add(Setting(key="exchange_rate_phone", value="10"))

        db.commit()
        print("初期データ投入完了")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
