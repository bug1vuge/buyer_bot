const DOMContentLoad = () => {

    const masksInitialization = () => {
        [].forEach.call( document.querySelectorAll('input[type="tel"]'), function(input) {
        var keyCode;
        function mask(event) {
            event.keyCode && (keyCode = event.keyCode);
            var pos = this.selectionStart;
            if (pos < 3) event.preventDefault();
            var matrix = "+7 (___) ___ ____",
                i = 0,
                def = matrix.replace(/\D/g, ""),
                val = this.value.replace(/\D/g, ""),
                new_value = matrix.replace(/[_\d]/g, function(a) {
                    return i < val.length ? val.charAt(i++) : a
                });
            i = new_value.indexOf("_");
            if (i != -1) {
                i < 5 && (i = 3);
                new_value = new_value.slice(0, i)
            }
            var reg = matrix.substr(0, this.value.length).replace(/_+/g,
                function(a) {
                    return "\\d{1," + a.length + "}"
                }).replace(/[+()]/g, "\\$&");
            reg = new RegExp("^" + reg + "$");
            if (!reg.test(this.value) || this.value.length < 5 || keyCode > 47 && keyCode < 58) {
            this.value = new_value;
            }
            if (event.type == "blur" && this.value.length < 5) {
            this.value = "";
            }
        }
    
        input.addEventListener("input", mask, false);
        input.addEventListener("focus", mask, false);
        input.addEventListener("blur", mask, false);
        input.addEventListener("keydown", mask, false);
    
        });
    }

    const modalInitialization = () => {

        const body = document.querySelector('body');
    
        const closeModal = () => {

            const modals = document.querySelectorAll('.modal');
            
            setTimeout(() => {

                modals.forEach(modal => {

                    if (modal.classList.contains('-js-visible')) {

                        const overlay = modal.querySelector('.modal__overlay');

                        modal.classList.remove('-js-visible');

                        body.style.overflow = 'visible';
                        body.style.paddingRight = 0;
                        overlay.style.paddingRight = 0;

                    };

                });

            }, 200);
        };

        const openModal = (obj) => {

            const modal = document.querySelector(obj.modal);
            const overlay = modal.querySelector('.modal__overlay');

            const paddingOffset = `${window.innerWidth - body.offsetWidth}px`;

            modal.classList.add('-js-visible');
            body.style.overflow = 'hidden';
            body.style.paddingRight = paddingOffset;
            overlay.style.paddingRight = paddingOffset;
            
        };

        const toggleModal = (e) => {

            const target = e.target;

            target.closest('.-js-personalData-modal') ? openModal({
                modal: '.personalData-modal',
            }) : '';

            target.closest('.modal__close-button') || target.classList.contains('modal__overlay') ? closeModal() : '';
        };

        document.addEventListener('click', toggleModal);

    };

    masksInitialization();
    modalInitialization();
};


document.addEventListener('DOMContentLoaded', DOMContentLoad);