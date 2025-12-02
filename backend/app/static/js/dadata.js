document.addEventListener("DOMContentLoaded", () => {
    const token = window.DADATA_TOKEN;

    if (!token) {
        console.error("DaData token not loaded");
        return;
    }

    $("#city").suggestions({
        token: token,
        type: "address",
        minChars: 3,
        hint: false,
        bounds: "city-settlement",
        onSelect: (suggestion) => {
            if (suggestion.data.city) {
                $("#city").val(suggestion.data.city);
            } else if (suggestion.data.settlement) {
                $("#city").val(suggestion.data.settlement);
            }
        }
    });

    $("#address").suggestions({
        token: token,
        type: "address",
        minChars: 3,
        hint: false,
        onSelect: (suggestion) => {
            if (suggestion.data.city) {
                $("#city").val(suggestion.data.city);
            }

            if (suggestion.data.postal_code) {
                let indexField = document.getElementById('postcode');
                if (indexField) indexField.value = suggestion.data.postal_code;
                if (indexField) indexField.classList.remove('input-error');
                if (indexField) indexField.classList.add('input-success');
            }
        }
    });
});