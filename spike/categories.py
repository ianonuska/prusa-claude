"""Guided-interview definitions + representative test specs.

The interview is the part of the product that makes a non-expert produce a
precise spec: pick a category, answer multiple-choice design questions, and
enter real measured dimensions. Each category's question set is data, so it is
cheap to add categories and to refine them as we learn what produces reliable
output.

CATEGORIES drives the (future) UI interview. SAMPLE_SPECS are completed
interviews used to validate the generation core right now.
"""

# ---- Guided interview definitions (the UI would render these) ----
# choice  -> multiple choice (drop-down / radio)
# measure -> a number the user must physically measure, in mm

CATEGORIES = {
    "phone_stand": {
        "label": "Phone / tablet stand",
        "questions": [
            {"id": "orientation", "type": "choice",
             "prompt": "How is the device held?",
             "options": ["portrait", "landscape", "either"]},
            {"id": "angle_deg", "type": "choice",
             "prompt": "Viewing angle from vertical?",
             "options": ["30", "45", "60"]},
            {"id": "cable_slot", "type": "choice",
             "prompt": "Charging cable pass-through?",
             "options": ["yes", "no"]},
        ],
        "measurements": [
            {"id": "device_width", "prompt": "Width of the device WITH case (mm)"},
            {"id": "device_thickness", "prompt": "Thickness WITH case (mm)"},
            {"id": "lip_height", "prompt": "Front lip height to retain device (mm)"},
        ],
    },
    "wall_bracket": {
        "label": "Wall / surface mount bracket",
        "questions": [
            {"id": "screw_size", "type": "choice",
             "prompt": "Mounting screw size?",
             "options": ["M2.5", "M3", "M4"]},
            {"id": "vent_holes", "type": "choice",
             "prompt": "Ventilation slots in the cradle?",
             "options": ["yes", "no"]},
        ],
        "measurements": [
            {"id": "board_width", "prompt": "Device width (mm)"},
            {"id": "board_length", "prompt": "Device length (mm)"},
            {"id": "hole_dx", "prompt": "Mount-hole spacing, horizontal (mm)"},
            {"id": "hole_dy", "prompt": "Mount-hole spacing, vertical (mm)"},
            {"id": "standoff_height", "prompt": "Standoff height under board (mm)"},
        ],
    },
    "knob": {
        "label": "Replacement knob",
        "questions": [
            {"id": "shaft_type", "type": "choice",
             "prompt": "Shaft type?",
             "options": ["D-shaft", "round", "splined"]},
            {"id": "grip", "type": "choice",
             "prompt": "Grip style?",
             "options": ["knurled", "smooth", "finger-wings"]},
        ],
        "measurements": [
            {"id": "knob_diameter", "prompt": "Knob outer diameter (mm)"},
            {"id": "knob_height", "prompt": "Knob height (mm)"},
            {"id": "shaft_diameter", "prompt": "Shaft diameter (mm)"},
            {"id": "d_flat_depth", "prompt": "Depth across the D-flat (mm)"},
        ],
    },
    "cable_clip": {
        "label": "Desk-edge cable organizer",
        "questions": [
            {"id": "mount", "type": "choice",
             "prompt": "How does it attach?",
             "options": ["clamp-over-edge", "screw-down", "adhesive-pad"]},
        ],
        "measurements": [
            {"id": "desk_thickness", "prompt": "Desk edge thickness (mm)"},
            {"id": "num_channels", "prompt": "Number of cable channels"},
            {"id": "cable_diameter", "prompt": "Largest cable diameter (mm)"},
        ],
    },
}


# ---- Completed interviews, used to validate generation now ----
# Real measurements, exactly the kind of input the guided UI would collect.

SAMPLE_SPECS = [
    {
        "id": "phone_stand_iphone15pro",
        "category": "phone_stand",
        "description": "Desk stand for an iPhone 15 Pro in a slim case",
        "answers": {"orientation": "portrait", "angle_deg": "60", "cable_slot": "yes"},
        "measurements": {
            "device_width": 71.5,
            "device_thickness": 12.0,
            "lip_height": 9.0,
        },
        "notes": "Angle is measured from vertical. Cable slot exits the back.",
    },
    {
        "id": "pi5_wall_bracket",
        "category": "wall_bracket",
        "description": "Wall mount for a Raspberry Pi 5, board parallel to wall",
        "answers": {"screw_size": "M3", "vent_holes": "yes"},
        "measurements": {
            "board_width": 56.0,
            "board_length": 85.0,
            "hole_dx": 58.0,
            "hole_dy": 49.0,
            "standoff_height": 6.0,
        },
        "notes": "Pi mounting holes are 2.7 mm; use threaded-into-plastic posts.",
    },
    {
        "id": "stove_knob_dshaft",
        "category": "knob",
        "description": "Replacement control knob for a D-shaft potentiometer",
        "answers": {"shaft_type": "D-shaft", "grip": "knurled"},
        "measurements": {
            "knob_diameter": 25.0,
            "knob_height": 18.0,
            "shaft_diameter": 6.0,
            "d_flat_depth": 4.5,
        },
        "notes": "Shaft hole needs a snug fit so the knob doesn't slip.",
    },
    {
        "id": "desk_cable_clip_4ch",
        "category": "cable_clip",
        "description": "Clip-over-edge organizer for four desk cables",
        "answers": {"mount": "clamp-over-edge"},
        "measurements": {
            "desk_thickness": 25.0,
            "num_channels": 4,
            "cable_diameter": 6.0,
        },
        "notes": "Clamp should grip the edge by friction, channels open upward.",
    },
]
