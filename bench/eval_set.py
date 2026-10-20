"""Throughput prompts and quality questions (scored by case-insensitive substring match)."""

_TOPICS = [
    "solar panels", "coffee roasting", "the history of the bicycle", "machine learning", "volcanoes",
    "remote work", "honeybees", "the stock market", "electric cars", "the Roman Empire", "sleep",
    "cloud computing", "chess openings", "ocean tides", "vaccines", "jazz music", "recycling plastic",
    "the moon landing", "sourdough bread", "cybersecurity", "rainforests", "startup fundraising",
    "black holes", "marathon training", "3D printing", "the printing press", "photosynthesis",
    "customer support", "earthquakes", "password managers", "public libraries", "wind turbines",
]
_TEMPLATES = [
    "Write a short paragraph explaining {t} to a beginner.",
    "List five interesting facts about {t}.",
    "Write a brief product pitch related to {t}.",
    "Summarize the pros and cons of {t} in a few sentences.",
]
# 32 topics x 4 templates = 128 prompts
THROUGHPUT_PROMPTS = [tpl.format(t=t) for tpl in _TEMPLATES for t in _TOPICS]
OUTPUT_TOKENS = 256  # fixed output length per prompt so configs are compared fairly

# (question, accepted answers)
QUALITY_QUESTIONS = [
    ("What is the capital of France?", ["paris"]),
    ("What is 12 multiplied by 12?", ["144"]),
    ("What is the chemical symbol for gold?", ["au"]),
    ("How many days are in a leap year?", ["366"]),
    ("What is the largest planet in our solar system?", ["jupiter"]),
    ("What is 15 plus 27?", ["42"]),
    ("Who wrote Romeo and Juliet?", ["shakespeare"]),
    ("At sea level, what is the boiling point of water in degrees Celsius?", ["100"]),
    ("What is the square root of 169?", ["13"]),
    ("What is the capital of Japan?", ["tokyo"]),
    ("How many continents are there on Earth?", ["7", "seven"]),
    ("What is 100 minus 37?", ["63"]),
    ("What is the fastest land animal?", ["cheetah"]),
    ("What is 7 times 8?", ["56"]),
    ("What gas do plants absorb from the air for photosynthesis?", ["carbon dioxide", "co2"]),
    ("What is the capital of Australia?", ["canberra"]),
    ("What is 9 squared?", ["81"]),
    ("Which planet is known as the Red Planet?", ["mars"]),
    ("How many sides does a hexagon have?", ["6", "six"]),
    ("What is 250 divided by 5?", ["50"]),
    # Harder multi-step arithmetic: where compressed small models tend to slip
    ("What is 23 multiplied by 17?", ["391"]),
    ("What is 1234 plus 5678?", ["6912"]),
    ("A train travels at 60 miles per hour for 3.5 hours. How many miles does it travel?", ["210"]),
    ("What is 15 percent of 240?", ["36"]),
    ("What is 2 raised to the power of 10?", ["1024", "1,024"]),
    ("A rectangle is 14 cm long and 9 cm wide. What is its area in square centimeters?", ["126"]),
    ("What is 1000 minus 387?", ["613"]),
    ("You buy 3 dozen eggs and break 7. How many eggs are left?", ["29"]),
    ("What is 19 squared?", ["361"]),
    ("What is 7 factorial?", ["5040", "5,040"]),
]
